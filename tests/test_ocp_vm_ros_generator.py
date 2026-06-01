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
import statistics
import tempfile
from unittest import TestCase

from nise.generators.ocp.ocp_generator import OCP_ROS_VM_COLUMNS
from nise.generators.ocp.ocp_generator import OCP_ROS_VM_GPU_DEVICE
from nise.generators.ocp.ocp_generator import OCP_ROS_VM_GPU_DEVICE_COLUMNS
from nise.generators.ocp.ocp_generator import OCP_ROS_VM_USAGE
from nise.generators.ocp.ocp_vm_ros_generator import OCPVirtualMachineGenerator
from nise.report import _ensure_vm_ros_generator
from nise.report import _get_generators
from nise.report import _static_report_has_vm_generator
from nise.report import ocp_create_report


def _interval_hour(interval_start):
    """Extract hour from OCP VM ROS interval_start timestamp."""
    return int(interval_start[11:13])


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
                {
                    "vm_name": "vm-abandoned",
                    "namespace": "forgotten-project",
                    "node_name": "worker-1",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "vcpu": 4,
                    "memory_gib": 8,
                    "disk_gib": 50,
                    "abandoned": True,
                },
            ]
        }

    def test_generates_quarter_hourly_rows(self):
        """Each VM produces 96 rows per day for the configured date range."""
        generator = OCPVirtualMachineGenerator(self.start, self.end, self.attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        # 2 days * 96 intervals/day * 4 VMs
        self.assertEqual(len(rows), 2 * 96 * 4)

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

    def test_agent_install_hour_defers_guest_columns(self):
        """Rows before agent_install_hour have empty guest-agent columns."""
        attributes = {
            "vms": [
                {
                    "vm_name": "late-agent",
                    "namespace": "production",
                    "guest_agent": True,
                    "agent_install_hour": 2,
                    "vcpu": 2,
                    "memory_gib": 4,
                    "disk_gib": 20,
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        before = [r for r in rows if r["interval_start"].startswith("2026-05-01 00:")]
        after = [r for r in rows if r["interval_start"].startswith("2026-05-01 02:")]
        self.assertTrue(before)
        self.assertTrue(after)
        self.assertEqual(before[0]["memory_available_kib"], "")
        self.assertNotEqual(after[0]["memory_available_kib"], "")

    def test_agent_remove_day_clears_guest_columns(self):
        """Rows on or after agent_remove_day have empty guest-agent columns."""
        attributes = {
            "vms": [
                {
                    "vm_name": "removed-agent",
                    "namespace": "staging",
                    "guest_agent": False,
                    "agent_remove_day": 1,
                    "vcpu": 2,
                    "memory_gib": 4,
                    "disk_gib": 20,
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        day0 = [r for r in rows if r["interval_start"].startswith("2026-05-01 ")]
        day1 = [r for r in rows if r["interval_start"].startswith("2026-05-02 ")]
        self.assertTrue(day0)
        self.assertTrue(day1)
        self.assertNotEqual(day0[0]["memory_available_kib"], "")
        self.assertEqual(day1[0]["memory_available_kib"], "")

    def test_abandoned_vm_zero_usage(self):
        """Abandoned VMs have zero CPU and memory usage for every interval."""
        generator = OCPVirtualMachineGenerator(self.start, self.end, self.attributes)
        rows = [r for r in generator.generate_data(OCP_ROS_VM_USAGE) if r["vm_name"] == "vm-abandoned"]
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(int(row["cpu_usage_mc"]), 0)
            self.assertEqual(int(row["memory_usage_kib"]), 0)
            self.assertNotEqual(row["memory_available_kib"], "")
            self.assertNotEqual(row["filesystem_capacity_bytes"], "")

    def test_csv_header_matches_ros_backend(self):
        """Generated columns match ros-ocp-backend VM CSV expectations."""
        self.assertEqual(tuple(OCP_ROS_VM_COLUMNS), OCP_ROS_VM_COLUMNS)
        self.assertEqual(OCP_ROS_VM_COLUMNS[19], "restart_count")
        self.assertEqual(OCP_ROS_VM_COLUMNS[20], "gpu_count")
        self.assertEqual(OCP_ROS_VM_COLUMNS[30], "gpu_max_slices")
        self.assertEqual(OCP_ROS_VM_COLUMNS[31], "net_rx_bytes_per_sec")
        self.assertEqual(OCP_ROS_VM_COLUMNS[36], "net_tx_drops_per_sec")

    def test_crash_loop_vm_has_restart_count(self):
        """VMs with crash_loop=true should have restart_count > 0."""
        attributes = {
            "vms": [
                {
                    "vm_name": "crash-loop-vm",
                    "namespace": "production",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "crash_loop": True,
                    "vcpu": 4,
                    "memory_gib": 8,
                    "disk_gib": 100,
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        self.assertTrue(rows)
        for row in rows:
            self.assertGreater(int(row["restart_count"]), 0)

    def test_gpu_vm_generates_gpu_columns(self):
        """VMs with gpu_count > 0 populate GPU metric columns."""
        attributes = {
            "vms": [
                {
                    "vm_name": "gpu-test-vm",
                    "namespace": "ml",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "gpu_count": 1,
                    "gpu_model": "NVIDIA T4",
                    "gpu_utilization": "idle",
                    "vcpu": 4,
                    "memory_gib": 8,
                    "disk_gib": 100,
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        self.assertTrue(rows)
        row = rows[0]
        self.assertEqual(int(row["gpu_count"]), 1)
        self.assertEqual(row["gpu_model"], "NVIDIA T4")
        self.assertLess(float(row["gpu_utilization_avg"]), 0.05)

    def test_gpu_utilization_levels(self):
        """GPU utilization scenarios produce increasing utilization values."""
        levels = ["idle", "low", "medium", "high", "saturated"]
        prev_avg = -1.0
        for level in levels:
            attributes = {
                "vms": [
                    {
                        "vm_name": "gpu-vm",
                        "namespace": "ml",
                        "gpu_count": 1,
                        "gpu_utilization": level,
                        "vcpu": 4,
                        "memory_gib": 8,
                        "disk_gib": 100,
                    }
                ]
            }
            generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
            row = next(generator.generate_data(OCP_ROS_VM_USAGE))
            avg = float(row["gpu_utilization_avg"])
            self.assertGreater(avg, prev_avg)
            prev_avg = avg

    def test_windows_update_spike_alternates_usage(self):
        """Windows VMs with windows_update_spike=true should have high variance in CPU."""
        attributes = {
            "vms": [
                {
                    "vm_name": "windows-spike-vm",
                    "namespace": "production",
                    "guest_os": "windows",
                    "guest_agent": True,
                    "windows_update_spike": True,
                    "vcpu": 4,
                    "memory_gib": 16,
                    "disk_gib": 200,
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        business_hour_rows = [r for r in rows if 8 <= _interval_hour(r["interval_start"]) < 18]
        self.assertTrue(business_hour_rows)
        cpu_values = {int(r["cpu_usage_mc"]) for r in business_hour_rows}
        self.assertGreater(len(cpu_values), 1)
        self.assertGreater(max(cpu_values) - min(cpu_values), 1000)

    def test_downsize_unstable_last_day_spike(self):
        """VMs with downsize_unstable=true should have higher usage on the last day."""
        start = datetime.datetime(2026, 5, 1, 0, 0, 0, tzinfo=datetime.UTC)
        end = datetime.datetime(2026, 5, 4, 0, 0, 0, tzinfo=datetime.UTC)
        attributes = {
            "vms": [
                {
                    "vm_name": "downsize-vm",
                    "namespace": "staging",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "downsize_unstable": True,
                    "vcpu": 8,
                    "memory_gib": 16,
                    "disk_gib": 100,
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(start, end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))

        def _business_hour_cpu(day_prefix):
            day_rows = [
                r
                for r in rows
                if r["interval_start"].startswith(day_prefix) and 8 <= _interval_hour(r["interval_start"]) < 18
            ]
            return [int(r["cpu_usage_mc"]) for r in day_rows]

        early_cpu = _business_hour_cpu("2026-05-01 ")
        early_cpu.extend(_business_hour_cpu("2026-05-02 "))
        last_day_cpu = _business_hour_cpu("2026-05-03 ")
        self.assertTrue(early_cpu)
        self.assertTrue(last_day_cpu)
        self.assertGreater(sum(last_day_cpu) / len(last_day_cpu), sum(early_cpu) / len(early_cpu) * 3)

    def test_fixed_usage_deterministic(self):
        """VMs with fixed_usage should produce consistent CPU/memory percentages."""
        attributes = {
            "vms": [
                {
                    "vm_name": "fixed-usage-vm",
                    "namespace": "production",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "vcpu": 4,
                    "memory_gib": 8,
                    "disk_gib": 100,
                    "fixed_usage": {"cpu_pct": 0.50, "mem_pct": 0.70},
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        cpu_request_mc = 4000
        memory_request_kib = 8 * 1024 * 1024
        expected_cpu = int(cpu_request_mc * 0.50)
        expected_mem = int(memory_request_kib * 0.70)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(int(row["cpu_usage_mc"]), expected_cpu)
            self.assertEqual(int(row["memory_usage_kib"]), expected_mem)

    def test_empty_guest_os_produces_empty_string(self):
        """VMs with guest_os="" should have empty guest_os in output rows."""
        attributes = {
            "vms": [
                {
                    "vm_name": "unknown-os-vm",
                    "namespace": "production",
                    "guest_os": "",
                    "guest_agent": False,
                    "vcpu": 2,
                    "memory_gib": 4,
                    "disk_gib": 50,
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["guest_os"], "")

    def test_restart_count_zero_for_non_crash_loop(self):
        """Normal VMs should have restart_count = 0."""
        attributes = {
            "vms": [
                {
                    "vm_name": "normal-vm",
                    "namespace": "production",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "vcpu": 4,
                    "memory_gib": 8,
                    "disk_gib": 100,
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(int(row["restart_count"]), 0)

    def test_gpu_device_csv_generation(self):
        """gpu_devices in YAML produces ocp_ros_vm_gpu_device rows with expected columns."""
        attributes = {
            "vms": [
                {
                    "vm_name": "multi-gpu-vm",
                    "namespace": "ml-training",
                    "node_name": "worker-gpu-1",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "vcpu": 16,
                    "memory_gib": 64,
                    "disk_gib": 500,
                    "gpu_devices": [
                        {
                            "uuid": "GPU-aaa-111",
                            "model": "NVIDIA A100-SXM4-80GB",
                            "utilization": "high",
                        },
                    ],
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_GPU_DEVICE))
        self.assertEqual(len(rows), 2 * 96 * 1)
        self.assertEqual(set(rows[0].keys()), set(OCP_ROS_VM_GPU_DEVICE_COLUMNS))
        self.assertEqual(rows[0]["vm_name"], "multi-gpu-vm")
        self.assertEqual(rows[0]["gpu_uuid"], "GPU-aaa-111")
        self.assertEqual(rows[0]["gpu_model"], "NVIDIA A100-SXM4-80GB")
        self.assertGreater(float(rows[0]["utilization_avg"]), 0)

    def test_gpu_device_csv_multi_gpu(self):
        """Two gpu_devices produce two rows per interval."""
        attributes = {
            "vms": [
                {
                    "vm_name": "multi-gpu-vm",
                    "namespace": "ml-training",
                    "node_name": "worker-gpu-1",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "vcpu": 16,
                    "memory_gib": 64,
                    "disk_gib": 500,
                    "gpu_devices": [
                        {"uuid": "GPU-aaa-111", "model": "NVIDIA A100", "utilization": "high"},
                        {"uuid": "GPU-bbb-222", "model": "NVIDIA A100", "utilization": "idle"},
                    ],
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_GPU_DEVICE))
        self.assertEqual(len(rows), 2 * 96 * 2)
        uuids_per_interval = {}
        for row in rows:
            key = row["interval_start"]
            uuids_per_interval.setdefault(key, set()).add(row["gpu_uuid"])
        for uuids in uuids_per_interval.values():
            self.assertEqual(uuids, {"GPU-aaa-111", "GPU-bbb-222"})

    def test_gpu_device_csv_no_gpu(self):
        """VMs without GPU config produce no device CSV rows."""
        attributes = {
            "vms": [
                {
                    "vm_name": "no-gpu-vm",
                    "namespace": "production",
                    "node_name": "worker-1",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "vcpu": 4,
                    "memory_gib": 8,
                    "disk_gib": 100,
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_GPU_DEVICE))
        self.assertEqual(rows, [])

    def test_variable_cpu_pattern(self):
        """cpu_pattern: variable yields high CPU usage coefficient of variation."""
        attributes = {
            "vms": [
                {
                    "vm_name": "variable-cpu-vm",
                    "namespace": "batch-jobs",
                    "node_name": "worker-1",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "vcpu": 4,
                    "memory_gib": 8,
                    "disk_gib": 100,
                    "cpu_pattern": "variable",
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        cpu_values = [int(r["cpu_usage_mc"]) for r in rows]
        self.assertGreater(len(cpu_values), 10)
        mean_cpu = statistics.mean(cpu_values)
        stdev_cpu = statistics.stdev(cpu_values)
        cv = stdev_cpu / mean_cpu if mean_cpu else 0
        self.assertGreater(cv, 0.35, f"expected high CPU variability, cv={cv:.3f}")

    def test_multi_gpu_mixed_utilization(self):
        """Per-device utilization scenarios produce distinct metric values."""
        attributes = {
            "vms": [
                {
                    "vm_name": "multi-gpu-mixed-vm",
                    "namespace": "ml-training",
                    "node_name": "worker-gpu-1",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "vcpu": 16,
                    "memory_gib": 64,
                    "disk_gib": 500,
                    "gpu_devices": [
                        {"uuid": "GPU-aaa-111", "utilization": "idle"},
                        {"uuid": "GPU-bbb-222", "utilization": "saturated"},
                    ],
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_GPU_DEVICE))
        by_uuid = {}
        for row in rows:
            by_uuid.setdefault(row["gpu_uuid"], []).append(float(row["utilization_avg"]))
        idle_avg = statistics.mean(by_uuid["GPU-aaa-111"])
        sat_avg = statistics.mean(by_uuid["GPU-bbb-222"])
        self.assertLess(idle_avg, sat_avg)
        self.assertLess(idle_avg, 0.05)
        self.assertGreater(sat_avg, 0.5)

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

    def test_low_io_disk_metrics(self):
        """low_io emits IOPS below ROS min classification threshold."""
        attributes = {
            "vms": [
                {
                    "vm_name": "cold-tier-vm",
                    "namespace": "default",
                    "node_name": "worker-1",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "vcpu": 2,
                    "memory_gib": 4,
                    "disk_gib": 50,
                    "low_io": True,
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        self.assertEqual(int(rows[0]["disk_read_iops"]), 20)
        self.assertEqual(int(rows[0]["disk_write_iops"]), 10)

    def test_power_off_candidate_mostly_idle(self):
        """power_off_candidate keeps most intervals below idle thresholds."""
        attributes = {
            "vms": [
                {
                    "vm_name": "power-off-vm",
                    "namespace": "default",
                    "node_name": "worker-1",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "vcpu": 4,
                    "memory_gib": 8,
                    "disk_gib": 100,
                    "power_off_candidate": True,
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        rows = list(generator.generate_data(OCP_ROS_VM_USAGE))
        cpu_values = [int(r["cpu_usage_mc"]) for r in rows]
        self.assertLess(max(cpu_values), 4000)

    def test_network_qos_sriov_metrics(self):
        """network_qos_sriov raises throughput and drops when network_heavy is set."""
        attributes = {
            "vms": [
                {
                    "vm_name": "sriov-vm",
                    "namespace": "default",
                    "node_name": "worker-1",
                    "guest_os": "linux",
                    "guest_agent": True,
                    "vcpu": 4,
                    "memory_gib": 8,
                    "disk_gib": 100,
                    "network_heavy": True,
                    "network_qos_sriov": True,
                }
            ]
        }
        generator = OCPVirtualMachineGenerator(self.start, self.end, attributes)
        row = next(generator.generate_data(OCP_ROS_VM_USAGE))
        self.assertEqual(int(row["net_rx_bytes_per_sec"]), 3_000_000_000)
        self.assertEqual(int(row["net_rx_drops_per_sec"]), 12_000)


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
