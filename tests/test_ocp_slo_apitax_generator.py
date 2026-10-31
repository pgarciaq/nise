"""Tests for the SLO and api-tax rollup generators (#728).

ros-openshift-slo-YYYYMM.csv and ros-openshift-apitax-YYYYMM.csv — the
operator's cumulative histogram emissions, consumed by robne
(librobne/csv/parse_slo.go, parse_apitax.go) for the headroom H leg
(#723) and the W5 api-tax advisory (#724). Byte-stable by design (the
capacity/nodepool precedent): fixed arithmetic, no faker.

The load-bearing contract (pinned here so nobody "fixes" it away): the
delta baseline is a snapshot strictly before the fire window, the hot
mass lands in the FINAL hours of the generation range, and one source
value means one coherent histogram.
"""

import csv
import os
import tempfile
import unittest
from datetime import datetime
from unittest import TestCase

from nise.generators.ocp.ocp_generator import OCPGenerator
from nise.generators.ocp.ocp_generator import OCP_HCP_SLO
from nise.generators.ocp.ocp_generator import OCP_HCP_SLO_COLUMNS
from nise.generators.ocp.ocp_generator import OCP_HCP_APITAX
from nise.generators.ocp.ocp_generator import OCP_HCP_APITAX_COLUMNS

HC = "hhhhhhhh-1111-1111-1111-111111111111"


def _slo_cfg(**over):
    cfg = {
        "source": "kubernetes",
        "hc_cluster_id": HC,
        "verb_groups": [
            {
                "verb_group": "mutating",
                "le_buckets": [0.1, 0.5, 1.0, 2.0, 3.0, 10.0],
                "baseline_per_hour": 100,
                "hot_final_hours": 1,
                "hot_le": 3.0,
                "hot_count": 1000,
            }
        ],
    }
    cfg.update(over)
    return cfg


def _apitax_cfg(**over):
    cfg = {
        "source": "kubernetes",
        "webhooks": [
            {
                "webhook_name": "slow.mutating.example",
                "le_buckets": [0.1, 0.5, 1.0, 2.0, 3.0, 10.0],
                "baseline_per_hour": 100,
                "hot_final_hours": 1,
                "hot_le": 3.0,
                "hot_count": 1000,
                "total_per_hour": 5000,
                "rejected_per_hour": 10,
            }
        ],
    }
    cfg.update(over)
    return cfg


class GenSloTest(TestCase):
    def setUp(self):
        self.start = datetime(2026, 10, 30, 0, 0, 0)
        self.end = datetime(2026, 10, 31, 0, 0, 0)

    def _rows(self, cfg):
        generator = OCPGenerator(self.start, self.end, {"slo": cfg}, ros_ocp_info=True)
        return list(generator.generate_data(OCP_HCP_SLO))

    def test_registered_with_attribute(self):
        generator = OCPGenerator(self.start, self.end, {"slo": {}}, ros_ocp_info=True)
        self.assertIn(OCP_HCP_SLO, generator.ocp_report_generation)

    def test_not_registered_without_attribute(self):
        generator = OCPGenerator(self.start, self.end, {}, ros_ocp_info=True)
        self.assertNotIn(OCP_HCP_SLO, generator.ocp_report_generation)

    def test_columns_contract(self):
        self.assertEqual(
            OCP_HCP_SLO_COLUMNS,
            (
                "hc_cluster_id",
                "window_start",
                "window_end",
                "verb_group",
                "le",
                "bucket_count",
                "collected_at",
                "source",
            ),
        )

    def test_one_row_per_hour_per_le_plus_inf(self):
        """24 hours x (6 finite les + the +Inf row) for one verb group."""
        rows = self._rows(_slo_cfg())
        self.assertEqual(len(rows), 24 * 7)
        les = {r["le"] for r in rows}
        self.assertEqual(les, {"0.1", "0.5", "1.0", "2.0", "3.0", "10.0", "+Inf"})
        self.assertTrue(all(r["hc_cluster_id"] == HC for r in rows))
        self.assertTrue(all(r["verb_group"] == "mutating" for r in rows))
        self.assertTrue(all(r["source"] == "kubernetes" for r in rows))

    def test_cumulative_growth_and_hot_tail(self):
        """Calm hours grow every le equally; the final hour concentrates at hot_le."""
        rows = self._rows(_slo_cfg())
        by_hour = {}
        for r in rows:
            by_hour.setdefault(r["window_start"].hour, {})[r["le"]] = r["bucket_count"]
        # Calm hour 5: every le at 6x100 (cumulative over hours 0-5).
        self.assertEqual(by_hour[5]["0.1"], 600)
        self.assertEqual(by_hour[5]["10.0"], 600)
        self.assertEqual(by_hour[5]["+Inf"], 600)
        # Final hour (23): 24x100 calm + hot mass at hot_le and above.
        self.assertEqual(by_hour[23]["0.1"], 2400, "small buckets keep the calm growth")
        self.assertEqual(by_hour[23]["3.0"], 2400 + 1000)
        self.assertEqual(by_hour[23]["10.0"], 2400 + 1000)
        self.assertEqual(by_hour[23]["+Inf"], 2400 + 1000)

    def test_collected_at_rides_window_end(self):
        rows = self._rows(_slo_cfg())
        row = next(r for r in rows if r["window_start"].hour == 5)
        self.assertEqual(row["collected_at"], row["window_end"].strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_deterministic(self):
        self.assertEqual(self._rows(_slo_cfg()), self._rows(_slo_cfg()))


class GenApiTaxTest(TestCase):
    def setUp(self):
        self.start = datetime(2026, 10, 30, 0, 0, 0)
        self.end = datetime(2026, 10, 31, 0, 0, 0)

    def _rows(self, cfg):
        generator = OCPGenerator(self.start, self.end, {"apitax": cfg}, ros_ocp_info=True)
        return list(generator.generate_data(OCP_HCP_APITAX))

    def test_registered_with_attribute(self):
        generator = OCPGenerator(self.start, self.end, {"apitax": {}}, ros_ocp_info=True)
        self.assertIn(OCP_HCP_APITAX, generator.ocp_report_generation)

    def test_columns_contract(self):
        self.assertEqual(
            OCP_HCP_APITAX_COLUMNS,
            (
                "webhook_name",
                "window_start",
                "window_end",
                "le",
                "bucket_count",
                "total_count",
                "rejected_count",
                "collected_at",
                "source",
            ),
        )

    def test_totals_denormalized_on_inf_row_only(self):
        """total/rejected ride the +Inf row; other rows carry empty strings."""
        rows = self._rows(_apitax_cfg())
        self.assertEqual(len(rows), 24 * 7)
        for r in rows:
            hour = r["window_start"].hour
            if r["le"] == "+Inf":
                self.assertEqual(r["total_count"], 5000 * (hour + 1), "cumulative totals")
                self.assertEqual(r["rejected_count"], 10 * (hour + 1))
            else:
                self.assertEqual(r["total_count"], "")
                self.assertEqual(r["rejected_count"], "")

    def test_hot_tail_and_quiet_webhook(self):
        """A quiet webhook (no hot spec) stays calm; the hot one concentrates."""
        cfg = _apitax_cfg()
        cfg["webhooks"].append(
            {
                "webhook_name": "calm.validating.example",
                "le_buckets": [0.1, 1.0],
                "baseline_per_hour": 50,
                "total_per_hour": 1000,
                "rejected_per_hour": 0,
            }
        )
        rows = self._rows(cfg)
        hot = [r for r in rows if r["webhook_name"] == "slow.mutating.example" and r["window_start"].hour == 23]
        calm = [r for r in rows if r["webhook_name"] == "calm.validating.example" and r["window_start"].hour == 23]
        hot_by_le = {r["le"]: r["bucket_count"] for r in hot}
        self.assertEqual(hot_by_le["3.0"], 2400 + 1000)
        calm_by_le = {r["le"]: r["bucket_count"] for r in calm}
        self.assertEqual(calm_by_le["1.0"], 50 * 24, "no hot spec: calm growth only")

    def test_deterministic(self):
        self.assertEqual(self._rows(_apitax_cfg()), self._rows(_apitax_cfg()))


class SloApitaxReportIntegrationTest(TestCase):
    def test_ocp_create_report_writes_contract_files(self):
        from nise.report import ocp_create_report

        with tempfile.TemporaryDirectory() as tmpdir:
            prev_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                options = {
                    "start_date": datetime(2026, 5, 1),
                    "end_date": datetime(2026, 5, 2),
                    "ocp_cluster_id": "test-hcp-cluster",
                    "ros_ocp_info": True,
                    "static_report_data": {
                        "generators": [
                            {
                                "OCPGenerator": {
                                    "start_date": "2026-05-01",
                                    "end_date": "2026-05-02",
                                    "slo": _slo_cfg(),
                                    "apitax": _apitax_cfg(),
                                }
                            }
                        ]
                    },
                    "row_limit": 100000,
                    "write_monthly": True,
                }
                ocp_create_report(options)
                for name, columns in (
                    ("ros-openshift-slo-202605.csv", OCP_HCP_SLO_COLUMNS),
                    ("ros-openshift-apitax-202605.csv", OCP_HCP_APITAX_COLUMNS),
                ):
                    expected = os.path.join(tmpdir, name)
                    self.assertTrue(os.path.isfile(expected), f"expected contract file {expected}")
                    with open(expected, newline="") as handle:
                        reader = csv.reader(handle)
                        header = next(reader)
                        rows = list(reader)
                    self.assertEqual(header, list(columns))
                    self.assertEqual(len(rows), 24 * 7, "one row per hour per le (incl +Inf)")
            finally:
                os.chdir(prev_cwd)


if __name__ == "__main__":
    unittest.main()
