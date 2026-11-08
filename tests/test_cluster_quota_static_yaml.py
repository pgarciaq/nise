"""Static cluster_resource_quotas YAML must reach the CRQ CSV without loss.

Issue #774: `_cluster_resource_quotas_from_static` copied only CPU/memory keys,
so supplied storage, pod/object counts and namespace membership silently fell
back to invented low-use defaults (storage 100 GiB/40 GiB, pods 50/20, objects
100/45, namespaces "namespace-1,namespace-2").

These tests go through YAML -> OCPGenerator -> CSV writer, not the row-builder
helper alone: the helper already accepted the fields, which is why helper-only
tests kept passing while the file lost them.
"""

import csv
import datetime
import os
import tempfile
import unittest

import yaml

from nise.generators.ocp.ocp_generator import (
    GIGABYTE,
    OCP_ROS_CLUSTER_QUOTA,
    OCP_ROS_CLUSTER_QUOTA_COLUMN,
    OCPGenerator,
)
from nise.report import _write_csv

EXAMPLE_CRQ_YAML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "examples",
    "ros_ocp_e2e",
    "ocp_report_cluster_quota.yml",
)


def _generate_crq_rows(cluster_resource_quotas):
    """Run the generator and return the rows it would write for CRQ."""
    start = datetime.datetime.now(datetime.UTC).replace(minute=0, second=0, microsecond=0)
    end = start + datetime.timedelta(hours=1)
    generator = OCPGenerator(
        start,
        end,
        {"cluster_resource_quotas": cluster_resource_quotas},
        ros_ocp_info=True,
    )
    return list(generator._gen_ros_cluster_quota_rows())


def _rows_as_csv(rows):
    """Write rows through the real CSV writer and read the cells back."""
    with tempfile.NamedTemporaryFile(mode="r", suffix=".csv", delete=False) as temp_file:
        path = temp_file.name
    try:
        _write_csv(path, rows, OCP_ROS_CLUSTER_QUOTA_COLUMN)
        with open(path) as csv_file:
            return list(csv.DictReader(csv_file))
    finally:
        os.unlink(path)


class ClusterQuotaStaticYamlTest(unittest.TestCase):
    def test_bytes_and_counts_from_static_yaml_reach_the_csv(self):
        """The issue's reproduction: supplied values must not become defaults."""
        rows = _generate_crq_rows(
            [
                {
                    "name": "demo-crq",
                    "cpu_request_hard": 20,
                    "cpu_request_used": 19,
                    "storage_request_hard": 1000000,
                    "storage_request_used": 990000,
                    "pods_hard": 1000,
                    "pods_used": 990,
                    "object_count_hard": 2000,
                    "object_count_used": 1980,
                    "namespaces": ["demo"],
                }
            ]
        )
        cells = _rows_as_csv(rows)[0]

        self.assertEqual(float(cells["storage_request_hard"]), 1000000)
        self.assertEqual(float(cells["storage_request_used"]), 990000)
        self.assertEqual(int(cells["pods_hard"]), 1000)
        self.assertEqual(int(cells["pods_used"]), 990)
        self.assertEqual(int(cells["object_count_hard"]), 2000)
        self.assertEqual(int(cells["object_count_used"]), 1980)
        self.assertEqual(cells["namespaces"], "demo")

    def test_storage_gig_alias_is_multiplied_and_wins_over_bytes(self):
        """`_gig` follows the memory convention: present wins over the bytes key."""
        rows = _generate_crq_rows(
            [
                {
                    "name": "alias-crq",
                    "storage_request_hard_gig": 500,
                    "storage_request_used_gig": 420,
                    "storage_request_hard": 536870912000 - 1,
                    "storage_request_used": 1,
                }
            ]
        )
        cells = _rows_as_csv(rows)[0]

        self.assertEqual(float(cells["storage_request_hard"]), 500 * GIGABYTE)
        self.assertEqual(float(cells["storage_request_used"]), 420 * GIGABYTE)

    def test_explicit_zero_object_quota_survives(self):
        """0 is an explicit "no object quota", not an absent key."""
        rows = _generate_crq_rows(
            [
                {
                    "name": "no-objects-crq",
                    "object_count_hard": 0,
                    "object_count_used": 0,
                }
            ]
        )
        cells = _rows_as_csv(rows)[0]

        self.assertEqual(int(cells["object_count_hard"]), 0)
        self.assertEqual(int(cells["object_count_used"]), 0)

    def test_absent_keys_keep_the_operator_aligned_defaults(self):
        """Control: a quota that omits the fields still gets the synthetic defaults."""
        rows = _generate_crq_rows([{"name": "bare-crq"}])
        cells = _rows_as_csv(rows)[0]

        self.assertEqual(float(cells["storage_request_hard"]), 100 * GIGABYTE)
        self.assertEqual(float(cells["storage_request_used"]), 40 * GIGABYTE)
        self.assertEqual(int(cells["pods_hard"]), 50)
        self.assertEqual(int(cells["pods_used"]), 20)
        self.assertEqual(int(cells["object_count_hard"]), 100)
        self.assertEqual(int(cells["object_count_used"]), 45)
        self.assertEqual(cells["namespaces"], "namespace-1,namespace-2")

    def test_bundled_e2e_fixture_emits_the_values_it_declares(self):
        """The shipped CRQ fixture must exercise what it says, not invented defaults."""
        with open(EXAMPLE_CRQ_YAML) as fixture:
            document = yaml.safe_load(fixture)
        attributes = document["generators"][0]["OCPGenerator"]

        cells = _rows_as_csv(_generate_crq_rows(attributes["cluster_resource_quotas"]))
        by_name = {cell["cluster_quota_name"]: cell for cell in cells}

        team = by_name["e2e-crq-team"]
        self.assertEqual(float(team["storage_request_hard"]), 500 * GIGABYTE)
        self.assertEqual(float(team["storage_request_used"]), 420 * GIGABYTE)
        self.assertEqual(int(team["pods_hard"]), 200)
        self.assertEqual(int(team["pods_used"]), 175)
        self.assertEqual(int(team["object_count_hard"]), 0)
        self.assertEqual(team["namespaces"], "crq-e2e-ns")

        platform = by_name["e2e-crq-platform"]
        self.assertEqual(float(platform["storage_request_hard"]), 1000 * GIGABYTE)
        self.assertEqual(int(platform["pods_used"]), 410)
        self.assertEqual(platform["namespaces"], "crq-e2e-ns,openshift-monitoring")

    def test_memory_gig_alias_wins_for_hard_and_used(self):
        """`_gig` beats its byte-named counterpart on both hard and used memory."""
        rows = _generate_crq_rows(
            [
                {
                    "name": "mem-alias-crq",
                    "memory_request_hard_gig": 50,
                    "memory_request_hard": 1,
                    "memory_request_used_gig": 45,
                    "memory_request_used": 1,
                    "memory_limit_hard_gig": 100,
                    "memory_limit_hard": 1,
                    "memory_limit_used_gig": 90,
                    "memory_limit_used": 1,
                }
            ]
        )
        cells = _rows_as_csv(rows)[0]

        self.assertEqual(float(cells["memory_request_hard"]), 50 * GIGABYTE)
        self.assertEqual(float(cells["memory_request_used"]), 45 * GIGABYTE)
        self.assertEqual(float(cells["memory_limit_hard"]), 100 * GIGABYTE)
        self.assertEqual(float(cells["memory_limit_used"]), 90 * GIGABYTE)

    def test_report_type_column_contract_is_unchanged(self):
        """Guard: the CSV header the ROS parser matches on must not drift."""
        self.assertIn("storage_request_hard", OCP_ROS_CLUSTER_QUOTA_COLUMN)
        self.assertIn("namespaces", OCP_ROS_CLUSTER_QUOTA_COLUMN)
        self.assertEqual(OCP_ROS_CLUSTER_QUOTA, "ocp_ros_cluster_quota")


if __name__ == "__main__":
    unittest.main()
