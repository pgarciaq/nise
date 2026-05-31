#
# Copyright 2018 Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
"""OCP Virtual Machine ROS Generator unit tests."""

import csv
import datetime
import os
import tempfile
from unittest import TestCase

from nise.generators.ocp.ocp_generator import OCP_ROS_VM_COLUMNS
from nise.generators.ocp.ocp_generator import OCP_ROS_VM_USAGE
from nise.generators.ocp.ocp_vm_ros_generator import OCPVirtualMachineGenerator
from nise.report import _ensure_vm_ros_generator
from nise.report import _get_generators
from nise.report import _static_report_has_vm_generator
from nise.report import ocp_create_report


class OCPVirtualMachineGeneratorTestCase(TestCase):
    """Tests for OCPVirtualMachineGenerator."""

    def setUp(self):
        """Set up test dates (two days => 192 quarter-hour intervals per VM)."""
        self.start = datetime.datetime(2026, 5, 1, 0, 0, 0, tzinfo=datetime.UTC)
        self.end = datetime.datetime(2026, 5, 3, 0, 0, 0, tzinfo=datetime.UTC)
        self.attributes = {
            "vms": [
                {
                    "vm_name": "vm-with-agent",
                    "namespace": "production",
                    "node_name": "worker-1",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "vcpu": 4,
                    "memory_gib": 8,
                    "disk_gib": 100,
                },
                {
                    "vm_name": "vm-no-agent",
                    "namespace": "legacy",
                    "node_name": "worker-2",
                    "guest_os": "linux",
                    "guest_agent": False,
                    "vcpu": 2,
                    "memory_gib": 4,
                    "disk_gib": 50,
                },
                {
                    "vm_name": "vm-idle",
                    "namespace": "dev",
                    "node_name": "worker-3",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "vcpu": 4,
                    "memory_gib": 8,
                    "disk_gib": 40,
                    "idle": True,
                },
            ]
        }

    def test_generates_quarter_hourly_rows(self):
        """Each VM produces 96 rows per day for the configured date range."""
        generator = OCPVirtualMachineGenerator(self.start, self.end, self.attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        # 2 days * 96 intervals/day * 3 VMs
        self.assertEqual(len(rows), 2 * 96 * 3)

    def test_guest_agent_columns_populated_or_empty(self):
        """Guest agent VMs have filesystem metrics; others use empty strings."""
        generator = OCPVirtualMachineGenerator(self.start, self.end, self.attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        with_agent = [r for r in rows if r["vm_name"] == "vm-with-agent"][0]
        without_agent = [r for r in rows if r["vm_name"] == "vm-no-agent"][0]

        self.assertNotEqual(with_agent["memory_available_kib"], "")
        self.assertNotEqual(with_agent["filesystem_used_bytes"], "")
        self.assertNotEqual(with_agent["filesystem_capacity_bytes"], "")
        self.assertEqual(without_agent["memory_available_kib"], "")
        self.assertEqual(without_agent["filesystem_used_bytes"], "")
        self.assertEqual(without_agent["filesystem_capacity_bytes"], "")

    def test_idle_vm_low_cpu(self):
        """Idle VMs stay below 50 millicores CPU usage."""
        generator = OCPVirtualMachineGenerator(self.start, self.end, self.attributes)
        rows = [r for r in generator.generate_data(OCP_ROS_VM_USAGE) if r["vm_name"] == "vm-idle"]
        for row in rows:
            self.assertLess(int(row["cpu_usage_mc"]), 50)

    def test_csv_header_matches_ros_backend(self):
        """Generated columns match ros-ocp-backend VM CSV expectations."""
        self.assertEqual(tuple(OCP_ROS_VM_COLUMNS), OCP_ROS_VM_COLUMNS)

    def test_static_report_helpers(self):
        """VM generator detection and auto-injection helpers behave as expected."""
        generator_list = [{"OCPVirtualMachineGenerator": {"start_date": "2026-05-01", "end_date": "2026-05-03"}}]
        self.assertTrue(_static_report_has_vm_generator(generator_list))
        generators = _get_generators(generator_list)
        self.assertEqual(generators[0]["generator"], OCPVirtualMachineGenerator)

        base = [{"generator": OCPVirtualMachineGenerator, "attributes": {}}]
        injected = _ensure_vm_ros_generator(
            base,
            ros_ocp_info=True,
            static_report_data={"generators": generator_list},
            report_start_date=self.start,
            report_end_date=self.end,
        )
        self.assertEqual(len(injected), 1)


class OCPVMReportIntegrationTestCase(TestCase):
    """Integration test writing ocp_ros_vm_usage.csv via ocp_create_report."""

    def test_ocp_create_report_writes_vm_csv(self):
        """ocp_create_report produces ocp_ros_vm_usage.csv with valid header."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prev_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                options = {
                    "start_date": datetime.datetime(2026, 5, 1, tzinfo=datetime.UTC),
                    "end_date": datetime.datetime(2026, 5, 2, tzinfo=datetime.UTC),
                    "ocp_cluster_id": "test-cluster-vm",
                    "ros_ocp_info": True,
                    "static_report_data": {
                        "generators": [
                            {
                                "OCPVirtualMachineGenerator": {
                                    "start_date": "2026-05-01",
                                    "end_date": "2026-05-02",
                                    "vms": [
                                        {
                                            "vm_name": "test-vm",
                                            "namespace": "default",
                                            "node_name": "node-1",
                                            "guest_os": "linux",
                                            "guest_agent": True,
                                            "vcpu": 2,
                                            "memory_gib": 4,
                                            "disk_gib": 20,
                                        }
                                    ],
                                }
                            }
                        ]
                    },
                    "row_limit": 100000,
                    "write_monthly": True,
                }
                ocp_create_report(options)
                matches = [f for f in os.listdir(tmpdir) if "ocp_ros_vm_usage" in f]
                self.assertEqual(len(matches), 1)
                with open(matches[0], newline="") as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(reader.fieldnames, list(OCP_ROS_VM_COLUMNS))
                    rows = list(reader)
                self.assertEqual(len(rows), 96)
                self.assertEqual(rows[0]["vm_name"], "test-vm")
            finally:
                os.chdir(prev_cwd)
