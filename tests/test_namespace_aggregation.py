"""Namespace ROS usage must aggregate the interval's container rows (#773).

Pre-fix, ``_aggregate_namespace_data`` averaged usage across pods, took a
single-pod maximum and ignored the interval entirely, so a namespace with two
0.5-core pods exported 0.5 cores instead of 1 core, and every fixture produced
a perfectly flat series regardless of what the container rows said.

The contract these tests assert: for every interval, the namespace row equals
the sum of the container rows emitted for that same interval. ``max``/``min``
are sums of the container extremes and therefore bounds on the true
within-interval aggregate, not sampled peaks (see the #773 design comment).
"""

import unittest
from datetime import datetime
from unittest import TestCase

from nise.generators.ocp.ocp_generator import OCPGenerator

START = datetime(2026, 10, 1, 0, 0, 0)
END = datetime(2026, 10, 2, 0, 0, 0)
GIB = 1024 * 1024 * 1024


def _pod(name, cpu=0.5, mem_gig=1.0, **extra):
    pod = {
        "pod_name": name,
        "workload": "deployment",
        "cpu_request": 1,
        "mem_request_gig": 1,
        "cpu_limit": 2,
        "mem_limit_gig": 2,
        "pod_seconds": 3600,
        "cpu_usage": {"full_period": cpu} if not isinstance(cpu, dict) else cpu,
        "mem_usage_gig": {"full_period": mem_gig},
    }
    pod.update(extra)
    return pod


def _node(pods, namespace="demo", node_name="n1"):
    return {
        "node_name": node_name,
        "cpu_cores": 32,
        "memory_gig": 64,
        "resource_id": 91000001,
        "namespaces": {namespace: {"pods": pods}},
    }


def _generator(pods, constant=True):
    return OCPGenerator(
        START,
        END,
        {"nodes": [_node(pods)]},
        ros_ocp_info=True,
        constant_values_ros_ocp=constant,
    )


def _generator_two_namespaces(first, second, constant=True):
    node = _node(first, namespace="alpha")
    node["namespaces"]["beta"] = {"pods": second}
    return OCPGenerator(
        START,
        END,
        {"nodes": [node]},
        ros_ocp_info=True,
        constant_values_ros_ocp=constant,
    )


def _rows(generator, report_type):
    return list(generator.generate_data(report_type))


def _sums_by_interval(rows, field):
    """Map interval_start -> sum of the field across rows in that interval."""
    out = {}
    for row in rows:
        out[row["interval_start"]] = out.get(row["interval_start"], 0.0) + float(row[field])
    return out


def _value_by_interval(rows, field):
    return {row["interval_start"]: float(row[field]) for row in rows}


class NamespaceAggregationTest(TestCase):
    def test_namespace_usage_is_the_sum_of_its_pods(self):
        """Namespace avg/max/min equal the container sums, not an average.

        Pre-fix this fixture exports 0.5 cores / 1 GiB (mean over two
        identical pods, single-pod max), so the equality assertion fails
        with the mean-vs-sum mechanism named by the value mismatch.
        """
        generator = _generator([_pod("web-a"), _pod("web-b")])
        containers = _rows(generator, "ocp_ros_usage")
        namespaces = _rows(generator, "ocp_ros_namespace_usage")

        self.assertEqual(len(namespaces), 96, "one namespace row per quarter hour")
        cpu_sums = _sums_by_interval(containers, "cpu_usage_container_avg")
        mem_sums = _sums_by_interval(containers, "memory_usage_container_avg")
        ns_cpu = _value_by_interval(namespaces, "cpu_usage_namespace_avg")
        ns_mem = _value_by_interval(namespaces, "memory_usage_namespace_avg")
        ns_max = _value_by_interval(namespaces, "cpu_usage_namespace_max")
        ns_min = _value_by_interval(namespaces, "cpu_usage_namespace_min")

        for interval in cpu_sums:
            with self.subTest(interval=interval):
                # Two identical 0.5-core pods: mean keeps 0.5, only the sum is 1.0.
                self.assertAlmostEqual(ns_cpu[interval], 1.0, places=5)
                self.assertAlmostEqual(ns_cpu[interval], cpu_sums[interval], places=5)
                self.assertAlmostEqual(ns_mem[interval], 2 * GIB, places=5)
                self.assertAlmostEqual(ns_mem[interval], mem_sums[interval], places=5)
                self.assertAlmostEqual(ns_max[interval], cpu_sums[interval], places=5)
                self.assertAlmostEqual(ns_min[interval], cpu_sums[interval], places=5)

        # Requests already summed pre-fix; keep them coherent with usage.
        self.assertEqual(float(namespaces[0]["cpu_request_namespace_sum"]), 2.0)
        self.assertEqual(float(namespaces[0]["memory_request_namespace_sum"]), 2 * GIB)

    def test_namespace_usage_scales_with_pod_count(self):
        """Fan-out control: usage must grow 1.0 -> 1.5 when the third pod appears.

        Equal-valued pods defeat max/distinct masking; only a sum is
        sensitive to the pod count.
        """
        two = _rows(_generator([_pod("web-a"), _pod("web-b")]), "ocp_ros_namespace_usage")
        three = _rows(
            _generator([_pod("web-a"), _pod("web-b"), _pod("web-c")]),
            "ocp_ros_namespace_usage",
        )

        two_cpu = _value_by_interval(two, "cpu_usage_namespace_avg")
        three_cpu = _value_by_interval(three, "cpu_usage_namespace_avg")
        first = sorted(two_cpu)[0]
        self.assertAlmostEqual(two_cpu[first], 1.0, places=5)
        self.assertAlmostEqual(three_cpu[first], 1.5, places=5)
        self.assertGreater(three_cpu[first], two_cpu[first])
        self.assertEqual(float(three[0]["cpu_request_namespace_sum"]), 3.0)

    def test_namespace_usage_is_order_independent(self):
        """Reversing pod insertion order cannot change the aggregate.

        Guards against any order-dependent fold (first/last wins) in the
        accumulation path.
        """
        forward = _rows(
            _generator([_pod("web-a", cpu=0.25), _pod("web-b", cpu=0.75)]),
            "ocp_ros_namespace_usage",
        )
        reverse = _rows(
            _generator([_pod("web-b", cpu=0.75), _pod("web-a", cpu=0.25)]),
            "ocp_ros_namespace_usage",
        )

        forward_cpu = _value_by_interval(forward, "cpu_usage_namespace_avg")
        reverse_cpu = _value_by_interval(reverse, "cpu_usage_namespace_avg")
        self.assertEqual(set(forward_cpu), set(reverse_cpu))
        for interval in forward_cpu:
            with self.subTest(interval=interval):
                self.assertAlmostEqual(forward_cpu[interval], 1.0, places=5)
                self.assertAlmostEqual(forward_cpu[interval], reverse_cpu[interval], places=5)

    def test_namespaces_do_not_bleed_into_each_other(self):
        """Per-namespace sums are keyed independently.

        Alpha has two 0.5-core pods (sum 1.0), beta one 1.0-core pod (sum
        1.0). Pre-fix alpha reports its mean 0.5; a keying bug in the
        accumulator would make both namespaces read the same total.
        """
        generator = _generator_two_namespaces(
            [_pod("web-a"), _pod("web-b")],
            [_pod("api", cpu=1.0, mem_gig=2.0)],
        )
        namespaces = _rows(generator, "ocp_ros_namespace_usage")

        by_namespace = {}
        for row in namespaces:
            by_namespace.setdefault(row["namespace"], set()).add(round(float(row["cpu_usage_namespace_avg"]), 5))
        self.assertEqual(set(by_namespace), {"alpha", "beta"})
        self.assertEqual(by_namespace["alpha"], {1.0})
        self.assertEqual(by_namespace["beta"], {1.0})

        totals = {}
        for row in namespaces:
            totals.setdefault(row["namespace"], float(row["memory_usage_namespace_avg"]))
        self.assertAlmostEqual(totals["alpha"], 2 * GIB, places=5)
        self.assertAlmostEqual(totals["beta"], 2 * GIB, places=5)

    def test_namespace_max_and_min_sum_container_extremes(self):
        """Randomized pods: ns max/min are sums of the container max/min.

        Uses randomized values so the container min/avg/max differ. Pre-fix
        the namespace max equals the largest single pod's max, so the
        fan-out assertion (sum > max) fails.
        """
        generator = _generator([_pod("web-a"), _pod("web-b")], constant=False)
        containers = _rows(generator, "ocp_ros_usage")
        namespaces = _rows(generator, "ocp_ros_namespace_usage")

        max_sums = _sums_by_interval(containers, "cpu_usage_container_max")
        min_sums = _sums_by_interval(containers, "cpu_usage_container_min")
        per_row_max = {}
        for row in containers:
            per_row_max.setdefault(row["interval_start"], []).append(float(row["cpu_usage_container_max"]))
        ns_max = _value_by_interval(namespaces, "cpu_usage_namespace_max")
        ns_min = _value_by_interval(namespaces, "cpu_usage_namespace_min")

        for interval in max_sums:
            with self.subTest(interval=interval):
                self.assertAlmostEqual(ns_max[interval], max_sums[interval], places=5)
                self.assertAlmostEqual(ns_min[interval], min_sums[interval], places=5)
                # Sum of two positive maxima strictly exceeds either one, so
                # "largest single pod's max" cannot satisfy this.
                self.assertGreater(ns_max[interval], max(per_row_max[interval]))

    def test_namespace_throttle_statistics_sum_container_values(self):
        """Throttle avg/min/max are interval sums; min is a real minimum.

        Pre-fix: avg is the mean (0.2), max is the largest pod (0.4) and
        min is ``min()`` over the *averages* (0.1) — not a minimum at all.
        Fixture values are injected so the sums (0.4 / 0.06 / 0.6) are
        distinguishable from every pre-fix statistic.
        """
        generator = _generator([_pod("web-a"), _pod("web-b")])
        generator.ros_data["demo/web-a"].update(
            {"cpu_throttle_container_avg": 0.1, "cpu_throttle_container_min": 0.05, "cpu_throttle_container_max": 0.2}
        )
        generator.ros_data["demo/web-b"].update(
            {"cpu_throttle_container_avg": 0.3, "cpu_throttle_container_min": 0.01, "cpu_throttle_container_max": 0.4}
        )

        namespaces = _rows(generator, "ocp_ros_namespace_usage")
        row = namespaces[0]
        # min first: pre-fix it is min() over the per-pod *averages* (0.1),
        # not a minimum of the container minima, so this names that bug.
        self.assertAlmostEqual(float(row["cpu_throttle_namespace_min"]), 0.06, places=5)
        self.assertAlmostEqual(float(row["cpu_throttle_namespace_max"]), 0.6, places=5)
        self.assertAlmostEqual(float(row["cpu_throttle_namespace_avg"]), 0.4, places=5)

    def test_multi_gpu_pod_is_counted_once(self):
        """One row per gpu_uuid must not multiply the pod's namespace usage.

        The pods pass emits two rows for each two-GPU pod. Per-row
        accumulation would export 2.0 cores; per-pod accumulation exports
        1.0. Pre-fix the mean also gives 0.5, so both the old defect and a
        per-row regression fail this assertion.
        """
        gpus = [
            {"gpu_model": "Tesla T4", "gpu_memory_capacity_mib": 15360},
            {"gpu_model": "A100", "gpu_memory_capacity_mib": 40960},
        ]
        generator = _generator([_pod("web-a", gpus=gpus), _pod("web-b", gpus=gpus)])
        containers = _rows(generator, "ocp_ros_usage")
        namespaces = _rows(generator, "ocp_ros_namespace_usage")

        self.assertEqual(len(containers), 96 * 4, "two pods x two GPUs x 96 intervals")
        first = namespaces[0]
        self.assertAlmostEqual(float(first["cpu_usage_namespace_avg"]), 1.0, places=5)
        self.assertAlmostEqual(float(first["memory_usage_namespace_avg"]), 2 * GIB, places=5)
        self.assertEqual(float(first["namespace_total_pods_avg"]), 2.0)

    def test_namespace_usage_tracks_by_hour_container_values(self):
        """A by_hour pod's namespace row follows the interval, not a placeholder.

        Pre-fix the namespace reads the pod template's stored average (a
        random placeholder for by_hour pods, since only ``full_period`` is
        understood there), so the series is flat and equals neither
        0.35 nor 0.0002.
        """
        pod = _pod("web-a", cpu={"by_hour": {"9-17": 0.35, "default": 0.0002}})
        generator = _generator([pod])
        containers = _rows(generator, "ocp_ros_usage")
        namespaces = _rows(generator, "ocp_ros_namespace_usage")

        container_by_interval = _value_by_interval(containers, "cpu_usage_container_avg")
        ns_by_interval = _value_by_interval(namespaces, "cpu_usage_namespace_avg")

        for interval, container_value in container_by_interval.items():
            with self.subTest(interval=interval):
                self.assertAlmostEqual(ns_by_interval[interval], container_value, places=5)

        self.assertEqual({round(v, 5) for v in ns_by_interval.values()}, {0.35, 0.0002})

    def test_randomized_namespace_rows_match_every_interval(self):
        """Randomized run: avg/max/min/memory equal the container sums everywhere.

        Coordination rule for time-varying samples: the namespace row is
        built from the same emitted row the container file carries, so no
        second randomization pass can drift from it.
        """
        generator = _generator([_pod("web-a"), _pod("web-b")], constant=False)
        containers = _rows(generator, "ocp_ros_usage")
        namespaces = _rows(generator, "ocp_ros_namespace_usage")

        fields = {
            "cpu_usage_namespace_avg": "cpu_usage_container_avg",
            "cpu_usage_namespace_max": "cpu_usage_container_max",
            "cpu_usage_namespace_min": "cpu_usage_container_min",
            "memory_usage_namespace_avg": "memory_usage_container_avg",
            "memory_rss_usage_namespace_avg": "memory_rss_usage_container_avg",
        }
        ns_values = {field: _value_by_interval(namespaces, field) for field in fields}
        for ns_field, container_field in fields.items():
            sums = _sums_by_interval(containers, container_field)
            for interval in sums:
                with self.subTest(field=ns_field, interval=interval):
                    self.assertAlmostEqual(ns_values[ns_field][interval], sums[interval], places=5)

        # Per-interval variation: pre-fix exported exactly one distinct value.
        self.assertGreater(
            len({round(v, 5) for v in ns_values["cpu_usage_namespace_avg"].values()}),
            1,
            "namespace series must vary with the interval",
        )


class NamespaceDirectGenerationTest(TestCase):
    """Namespace-only generation falls back to base values (documented)."""

    def test_direct_namespace_generation_sums_base_values(self):
        """No pods pass: resolve each pod's base value and sum it.

        The fallback must still apply the sum rule. Pre-fix it exported the
        two-pod mean, 0.5 cores / 1 GiB.
        """
        generator = _generator([_pod("web-a"), _pod("web-b")])
        namespaces = _rows(generator, "ocp_ros_namespace_usage")

        self.assertEqual(len(namespaces), 96)
        first = namespaces[0]
        self.assertAlmostEqual(float(first["cpu_usage_namespace_avg"]), 1.0, places=5)
        self.assertAlmostEqual(float(first["memory_usage_namespace_avg"]), 2 * GIB, places=5)
        self.assertAlmostEqual(float(first["cpu_usage_namespace_max"]), 1.0, places=5)
        self.assertAlmostEqual(float(first["cpu_usage_namespace_min"]), 1.0, places=5)

    def test_direct_namespace_generation_resolves_by_hour(self):
        """No pods pass: the fallback still shapes cpu usage per interval."""
        pod = _pod("web-a", cpu={"by_hour": {"9-17": 0.35, "default": 0.0002}})
        generator = _generator([pod])
        namespaces = _rows(generator, "ocp_ros_namespace_usage")

        values = {round(float(row["cpu_usage_namespace_avg"]), 5) for row in namespaces}
        self.assertEqual(values, {0.35, 0.0002})


class NamespaceReportIntegrationTest(TestCase):
    """The CLI path (report.py) drives pods before namespace on one generator.

    The unit tests call ``generate_data`` directly; only this path proves that
    the accumulator the CLI relies on is actually armed and consumed, and that
    the two written CSVs agree.
    """

    def test_ocp_create_report_namespace_csv_sums_container_rows(self):
        """Written CSVs: every namespace row equals its interval's container sums."""
        import csv
        import os
        import tempfile
        from collections import defaultdict

        from nise.report import ocp_create_report

        options = {
            "start_date": datetime(2026, 5, 1),
            "end_date": datetime(2026, 5, 2),
            "ocp_cluster_id": "e2e-773",
            "ros_ocp_info": True,
            "constant_values_ros_ocp": True,
            "static_report_data": {
                "generators": [
                    {
                        "OCPGenerator": {
                            "start_date": "2026-05-01",
                            "end_date": "2026-05-02",
                            "nodes": [_node([_pod("web-a"), _pod("web-b")])],
                        }
                    }
                ]
            },
            "row_limit": 100000,
            "write_monthly": True,
        }

        def read(name):
            with open(name, newline="") as handle:
                return list(csv.DictReader(handle))

        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                ocp_create_report(options)
                pod_rows = read("May-2026-e2e-773-ocp_ros_usage.csv")
                namespace_rows = read("May-2026-e2e-773-ocp_ros_namespace_usage.csv")
            finally:
                os.chdir(previous_cwd)

        sums = defaultdict(lambda: defaultdict(float))
        pods_per_interval = defaultdict(int)
        for row in pod_rows:
            key = (row["interval_start"], row["namespace"])
            for container_column in ("cpu_usage_container_avg", "memory_usage_container_avg"):
                sums[key][container_column] += float(row[container_column])
            pods_per_interval[key] += 1

        self.assertEqual(len(namespace_rows), 96)
        for row in namespace_rows:
            key = (row["interval_start"], row["namespace"])
            with self.subTest(interval=row["interval_start"]):
                self.assertAlmostEqual(
                    float(row["cpu_usage_namespace_avg"]), sums[key]["cpu_usage_container_avg"], places=5
                )
                self.assertAlmostEqual(
                    float(row["memory_usage_namespace_avg"]), sums[key]["memory_usage_container_avg"], places=5
                )
                self.assertAlmostEqual(float(row["cpu_request_namespace_sum"]), 2.0, places=5)
                self.assertEqual(int(float(row["namespace_total_pods_avg"])), pods_per_interval[key])


if __name__ == "__main__":
    unittest.main()
