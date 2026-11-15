"""Namespace ResourceQuota storage must accept the ``_gig`` spelling (#824).

``resource_quota`` in static OCP YAML accepted only the byte spelling for
storage, while the sibling ``cluster_resource_quotas`` block accepted both
(#823). A fixture author copying the cluster idiom therefore got the 50 GiB
default with no error and no warning:

    resource_quota:
      storage_request_hard_gig: 100    # ignored before this fix

Two things these tests pin beyond the alias:

* the namespace path keeps **its own** 50 GiB default. The CRQ default is
  100 GiB, so a copy-paste of the cluster call would silently raise this
  default — the control test fails if the constant is ever shared.
* both spellings are asserted through the namespace CSV writer, not only on
  the row builder: #823 showed helper-only tests keep passing while the file
  loses the field.
"""

import csv
import os
import tempfile
import unittest
from datetime import datetime
from unittest import TestCase

from nise.generators.ocp.ocp_generator import (
    OCP_ROS_NAMESPACE_USAGE_COLUMN,
    OCPGenerator,
    namespace_quota_extended_values,
)
from nise.report import _write_csv

START = datetime(2026, 10, 1, 0, 0, 0)
END = datetime(2026, 10, 1, 1, 0, 0)
GIB = 1024**3

# The namespace path's own default, deliberately different from the CRQ
# default (100 GiB) so sharing one constant cannot go unnoticed.
NAMESPACE_STORAGE_DEFAULT_HARD = 50 * GIB


def _pod(name="web-a"):
    return {
        "pod_name": name,
        "workload": "deployment",
        "cpu_request": 1,
        "mem_request_gig": 1,
        "cpu_limit": 2,
        "mem_limit_gig": 2,
        "pod_seconds": 3600,
        "cpu_usage": {"full_period": 0.5},
        "mem_usage_gig": {"full_period": 1.0},
    }


def _namespace_rows(quota):
    """Generate the namespace-usage rows a fixture with this quota would emit."""
    node = {
        "node_name": "quota-worker-1",
        "cpu_cores": 32,
        "memory_gig": 64,
        "resource_id": 91000001,
        "namespaces": {"quota-ns": {"resource_quota": quota, "pods": [_pod()]}},
    }
    generator = OCPGenerator(
        START,
        END,
        {"nodes": [node]},
        ros_ocp_info=True,
        constant_values_ros_ocp=True,
    )
    return list(generator.generate_data("ocp_ros_namespace_usage"))


def _rows_as_csv(rows):
    """Write rows through the real CSV writer and read the cells back."""
    with tempfile.NamedTemporaryFile(mode="r", suffix=".csv", delete=False) as temp_file:
        path = temp_file.name
    try:
        _write_csv(path, rows, OCP_ROS_NAMESPACE_USAGE_COLUMN)
        with open(path) as csv_file:
            return list(csv.DictReader(csv_file))
    finally:
        os.unlink(path)


class NamespaceQuotaStorageAliasTest(TestCase):
    def test_gig_spelling_is_multiplied_and_wins_over_bytes(self):
        """`_gig` follows the memory convention: present wins over the bytes key."""
        values = namespace_quota_extended_values(
            {
                "storage_request_hard_gig": 500,
                "storage_request_used_gig": 420,
                "storage_request_hard": 1,
                "storage_request_used": 1,
            }
        )

        self.assertEqual(values["storage_request_namespace_hard"], 500 * GIB)
        self.assertEqual(values["storage_request_namespace_used"], 420 * GIB)

    def test_byte_spelling_alone_is_still_honoured(self):
        """The pre-existing byte spelling keeps working, unchanged."""
        values = namespace_quota_extended_values(
            {
                "storage_request_hard": 1000000,
                "storage_request_used": 990000,
            }
        )

        self.assertEqual(values["storage_request_namespace_hard"], 1000000)
        self.assertEqual(values["storage_request_namespace_used"], 990000)

    def test_absent_storage_keys_keep_the_namespace_default(self):
        """Control: no storage keys still means 50 GiB, not the CRQ 100 GiB."""
        values = namespace_quota_extended_values({"pods_hard": 10}, constant_values_ros_ocp=True)

        self.assertEqual(values["storage_request_namespace_hard"], NAMESPACE_STORAGE_DEFAULT_HARD)
        self.assertAlmostEqual(
            values["storage_request_namespace_used"],
            NAMESPACE_STORAGE_DEFAULT_HARD * 0.65,
            places=5,
        )

    def test_gig_spelling_reaches_the_namespace_csv(self):
        """The alias must survive the writer, not just the row builder."""
        rows = _namespace_rows(
            {
                "storage_request_hard_gig": 500,
                "storage_request_used_gig": 420,
            }
        )
        self.assertTrue(rows, "the fixture must emit namespace rows")

        cells = _rows_as_csv(rows)[0]
        self.assertEqual(float(cells["storage_request_namespace_hard"]), 500 * GIB)
        self.assertEqual(float(cells["storage_request_namespace_used"]), 420 * GIB)

    def test_quota_without_storage_keeps_its_cells_unchanged(self):
        """No fixture change is intended: a storage-less quota emits today's 50 GiB."""
        rows = _namespace_rows({"cpu_request_used": 2.0})

        cells = _rows_as_csv(rows)[0]
        self.assertEqual(
            float(cells["storage_request_namespace_hard"]),
            NAMESPACE_STORAGE_DEFAULT_HARD,
        )


if __name__ == "__main__":
    unittest.main()
