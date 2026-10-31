"""Tests for the NodePool rollup generator (#727).

ros-openshift-nodepool-YYYYMM.csv — the operator's NodePool rollup
emission, consumed by robne (librobne/csv/parse_nodepool.go) for the W8
sleep advisory's worker-node facts and the zombie short lane's
parked-pool readings (#674). Byte-stable by design (the capacity
precedent): no faker, fixed arithmetic.
"""

import csv
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import TestCase

from nise.generators.ocp.ocp_generator import OCPGenerator
from nise.generators.ocp.ocp_generator import OCP_HCP_NODEPOOL
from nise.generators.ocp.ocp_generator import OCP_HCP_NODEPOOL_COLUMNS


class GenHcpNodepoolTest(TestCase):
    """NodePool generator (ros-openshift-nodepool)."""

    def setUp(self):
        self.now = datetime(2026, 10, 27, 4, 0, 0)
        self.two_hours_ago = self.now - timedelta(hours=2)

    def test_registered_with_attribute(self):
        """ros_ocp_info + nodepool attribute registers the report type."""
        generator = OCPGenerator(self.two_hours_ago, self.now, {"nodepool": {}}, ros_ocp_info=True)
        self.assertIn(OCP_HCP_NODEPOOL, generator.ocp_report_generation)

    def test_registered_with_attribute_ros_only(self):
        generator = OCPGenerator(self.two_hours_ago, self.now, {"nodepool": {}}, ros_ocp_info=True, ros_only=True)
        self.assertIn(OCP_HCP_NODEPOOL, generator.ocp_report_generation)

    def test_not_registered_without_attribute(self):
        generator = OCPGenerator(self.two_hours_ago, self.now, {}, ros_ocp_info=True)
        self.assertNotIn(OCP_HCP_NODEPOOL, generator.ocp_report_generation)

    def test_not_registered_without_ros_ocp_info(self):
        generator = OCPGenerator(self.two_hours_ago, self.now, {"nodepool": {}})
        self.assertNotIn(OCP_HCP_NODEPOOL, generator.ocp_report_generation)

    def test_columns_contract(self):
        """The 9-column header matches the operator contract exactly, in order."""
        self.assertEqual(
            OCP_HCP_NODEPOOL_COLUMNS,
            (
                "hc_cluster_id",
                "pool_name",
                "window_start",
                "window_end",
                "spec_replicas",
                "status_replicas",
                "autoscaling",
                "collected_at",
                "source",
            ),
        )

    def _rows(self, nodepool_cfg, start=None, end=None):
        start = start or self.two_hours_ago
        end = end or self.now
        generator = OCPGenerator(start, end, {"nodepool": nodepool_cfg}, ros_ocp_info=True)
        return list(generator.generate_data(OCP_HCP_NODEPOOL))

    def test_one_row_per_hour_per_pool(self):
        """Two hours, two pools: four rows, hourly windows."""
        cfg = {
            "source": "hypershift",
            "pools": [
                {"hc_cluster_id": "hc-1", "pool_name": "workers", "spec_replicas": 2, "status_replicas": 2},
                {"hc_cluster_id": "hc-1", "pool_name": "infra", "spec_replicas": 1, "status_replicas": 1},
            ],
        }
        rows = self._rows(cfg)
        self.assertEqual(len(rows), 4, "2 hours x 2 pools")
        workers = next(r for r in rows if r["pool_name"] == "workers" and r["window_start"] == self.two_hours_ago)
        self.assertEqual(workers["hc_cluster_id"], "hc-1")
        self.assertEqual(workers["spec_replicas"], 2)
        self.assertEqual(workers["status_replicas"], 2)
        self.assertEqual(workers["autoscaling"], "")
        self.assertEqual(workers["source"], "hypershift")
        # Hourly window (KMO convention: end = start + 59m59s).
        self.assertEqual(workers["window_start"], self.two_hours_ago)
        self.assertEqual(workers["window_end"], self.two_hours_ago + timedelta(minutes=59, seconds=59))
        self.assertEqual(workers["collected_at"], workers["window_end"].strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_deterministic_bytes(self):
        """Same config, same clock: identical rows (no faker anywhere)."""
        cfg = {"pools": [{"hc_cluster_id": "hc-1", "pool_name": "workers", "spec_replicas": 0, "status_replicas": 0}]}
        self.assertEqual(self._rows(cfg), self._rows(cfg))

    def test_parked_pool_reads_zero(self):
        """The zombie short-lane fixture shape: spec=0 AND status=0."""
        cfg = {"pools": [{"hc_cluster_id": "hc-1", "pool_name": "workers", "spec_replicas": 0, "status_replicas": 0}]}
        for row in self._rows(cfg):
            self.assertEqual(row["spec_replicas"], 0)
            self.assertEqual(row["status_replicas"], 0)

    def test_day_overrides_apply(self):
        """Mid-transition fixture shape: day 1 scales while days 0/2 park."""
        cfg = {
            "pools": [
                {
                    "hc_cluster_id": "hc-1",
                    "pool_name": "workers",
                    "spec_replicas": 0,
                    "status_replicas": 0,
                    "day_overrides": [{"day": 1, "spec_replicas": 2, "status_replicas": 2}],
                }
            ],
        }
        start = datetime(2026, 10, 24, 0, 0, 0)
        end = datetime(2026, 10, 27, 0, 0, 0)
        rows = self._rows(cfg, start=start, end=end)
        by_day = {}
        for row in rows:
            by_day.setdefault(row["window_start"].date(), set()).add((row["spec_replicas"], row["status_replicas"]))
        self.assertEqual(by_day[datetime(2026, 10, 24).date()], {(0, 0)})
        self.assertEqual(by_day[datetime(2026, 10, 25).date()], {(2, 2)}, "day 1 override")
        self.assertEqual(by_day[datetime(2026, 10, 26).date()], {(0, 0)})

    def test_defaults(self):
        """Missing optional knobs fall back to the operator's defaults."""
        cfg = {"pools": [{"hc_cluster_id": "hc-1", "pool_name": "workers", "spec_replicas": 3}]}
        row = self._rows(cfg)[0]
        self.assertEqual(row["status_replicas"], 3, "status defaults to spec")
        self.assertEqual(row["source"], "hypershift")
        self.assertEqual(row["autoscaling"], "")


class NodepoolReportIntegrationTest(TestCase):
    """Integration: the nodepool CSV routes through ocp_create_report."""

    def test_ocp_create_report_writes_nodepool_csv(self):
        """ocp_create_report emits ros-openshift-nodepool-YYYYMM.csv (no cluster id, no -N part)."""
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
                                    "nodepool": {
                                        "pools": [
                                            {
                                                "hc_cluster_id": "hc-uuid-1",
                                                "pool_name": "workers",
                                                "spec_replicas": 2,
                                                "status_replicas": 2,
                                            }
                                        ]
                                    },
                                }
                            }
                        ]
                    },
                    "row_limit": 100000,
                    "write_monthly": True,
                }
                ocp_create_report(options)
                expected = os.path.join(tmpdir, "ros-openshift-nodepool-202605.csv")
                self.assertTrue(os.path.isfile(expected), f"expected contract file {expected}")
                with open(expected, newline="") as handle:
                    reader = csv.reader(handle)
                    header = next(reader)
                    rows = list(reader)
                self.assertEqual(header, list(OCP_HCP_NODEPOOL_COLUMNS))
                self.assertEqual(len(rows), 24, "one observation per hour of the day")
                self.assertEqual(rows[0][0], "hc-uuid-1")
                self.assertEqual(rows[0][1], "workers")
            finally:
                os.chdir(prev_cwd)


if __name__ == "__main__":
    unittest.main()
