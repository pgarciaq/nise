"""Tests for by-hour usage shaping (#727, the W8 guest-template enabler).

The sleep-advisory signature needs workloads active in business hours and
idle outside — constant `full_period` usage cannot express that (the
outside-BH leg reads All-minus-BH, so 24/7 usage breaks the signature).
The pod usage dict gains a `by_hour` shape: hour ranges ("9-17",
midnight-wrapping "22-6", single "3") map to values, with a `default`
for unmatched hours (0 when absent). Resolved at row time, so every hour
of the day carries its own usage. Deterministic: the by_hour override
bypasses the per-row randomization for the CPU usage columns.
"""

import unittest
from datetime import datetime
from unittest import TestCase

from nise.generators.ocp.ocp_generator import OCPGenerator

START = datetime(2026, 10, 27, 0, 0, 0)
END = datetime(2026, 10, 28, 0, 0, 0)


def _rows(pod_spec):
    """Generate one day of ROS container rows for a single-pod template."""
    # The unwrapped node shape _gen_nodes consumes (the YAML's `- node:`
    # wrapper is unwrapped upstream of the generator attributes).
    node = {
        "node_name": "w1",
        "cpu_cores": 8,
        "memory_gig": 32,
        "resource_id": 1,
        "namespaces": {"demo-app": {"pods": [pod_spec]}},
    }
    generator = OCPGenerator(START, END, {"nodes": [node]}, ros_ocp_info=True)
    return list(generator.generate_data("ocp_ros_usage"))


def _pod(cpu_usage):
    return {
        "pod_name": "web",
        "cpu_request": 2,
        "cpu_limit": 4,
        "mem_request_gig": 2,
        "mem_limit_gig": 4,
        "pod_seconds": 3600,
        "cpu_usage": cpu_usage,
        "mem_usage_gig": {"full_period": 1.0},
        "workload": "deployment",
    }


def _usage_by_hour(rows):
    """Map hour -> float(cpu_usage_container_avg)."""
    out = {}
    for row in rows:
        hour = datetime.strptime(row["interval_start"], "%Y-%m-%d %H:%M:%S %z %Z").hour
        out[hour] = float(row["cpu_usage_container_avg"])
    return out


class ByHourUsageTest(TestCase):
    def test_by_hour_daytime_active_night_idle(self):
        """The W8 signature shape: 09:00-17:00 busy, outside idle."""
        usage = _usage_by_hour(_rows(_pod({"by_hour": {"9-17": 0.35, "default": 0.001}})))
        self.assertEqual(len(usage), 24, "one row per hour")
        self.assertAlmostEqual(usage[9], 0.35, places=6)
        self.assertAlmostEqual(usage[12], 0.35, places=6)
        self.assertAlmostEqual(usage[16], 0.35, places=6)
        self.assertAlmostEqual(usage[2], 0.001, places=6)
        self.assertAlmostEqual(usage[23], 0.001, places=6)

    def test_by_hour_deterministic(self):
        """Same template, same rows: the by_hour override never randomizes."""
        first = _usage_by_hour(_rows(_pod({"by_hour": {"9-17": 0.35, "default": 0.001}})))
        second = _usage_by_hour(_rows(_pod({"by_hour": {"9-17": 0.35, "default": 0.001}})))
        self.assertEqual(first, second)

    def test_by_hour_wraparound_range(self):
        """A range crossing midnight (22-6) covers both sides."""
        usage = _usage_by_hour(_rows(_pod({"by_hour": {"22-6": 0.8, "default": 0.01}})))
        self.assertAlmostEqual(usage[23], 0.8, places=6)
        self.assertAlmostEqual(usage[5], 0.8, places=6)
        self.assertAlmostEqual(usage[12], 0.01, places=6)

    def test_by_hour_single_hour_key(self):
        usage = _usage_by_hour(_rows(_pod({"by_hour": {"3": 0.7, "default": 0.02}})))
        self.assertAlmostEqual(usage[3], 0.7, places=6)
        self.assertAlmostEqual(usage[4], 0.02, places=6)

    def test_by_hour_boundary_hours(self):
        """9-17 is inclusive start, exclusive end: 17:00 reads default."""
        usage = _usage_by_hour(_rows(_pod({"by_hour": {"9-17": 0.35, "default": 0.001}})))
        self.assertAlmostEqual(usage[9], 0.35, places=6)
        self.assertAlmostEqual(usage[17], 0.001, places=6)

    def test_by_hour_default_missing_reads_zero(self):
        """Unmatched hours without a default read zero (explicit idle)."""
        usage = _usage_by_hour(_rows(_pod({"by_hour": {"9-17": 0.35}})))
        self.assertAlmostEqual(usage[2], 0.0, places=6)

    def test_by_hour_clamped_to_limit(self):
        """Values above the pod's CPU limit clamp (the full_period rule)."""
        usage = _usage_by_hour(_rows(_pod({"by_hour": {"9-17": 99.0, "default": 0.001}})))
        self.assertAlmostEqual(usage[12], 4.0, places=6, msg="clamped to cpu_limit")

    def test_full_period_still_works(self):
        """The existing shape is unchanged (no by_hour key, no override)."""
        rows = _rows(_pod({"full_period": 0.5}))
        for row in rows:
            self.assertNotEqual(float(row["cpu_usage_container_avg"]), 0.0)


if __name__ == "__main__":
    unittest.main()
