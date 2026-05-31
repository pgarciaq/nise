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
"""OpenShift Virtualization ROS usage data generator (15-minute intervals)."""

import datetime
from random import randint
from random import uniform

from nise.generators.generator import AbstractGenerator
from nise.generators.generator import REPORT_TYPE
from nise.generators.ocp.ocp_generator import OCP_ROS_VM_COLUMNS
from nise.generators.ocp.ocp_generator import OCP_ROS_VM_USAGE
from nise.generators.ocp.ocp_generator import OCPGenerator

GIGABYTE = 1024 * 1024 * 1024
KIB_PER_GIB = 1024 * 1024
IDLE_LINUX_MEMORY_KIB = 512 * 1024
IDLE_WINDOWS_MEMORY_KIB = 3072 * 1024
DEFAULT_VMS = [
    {
        "vm_name": "web-server-linux-01",
        "namespace": "production",
        "node_name": "worker-1",
        "guest_os": "linux",
        "guest_agent": True,
        "vcpu": 4,
        "memory_gib": 8,
        "disk_gib": 100,
        "idle": False,
    },
    {
        "vm_name": "db-server-windows-01",
        "namespace": "production",
        "node_name": "worker-2",
        "guest_os": "windows",
        "guest_agent": True,
        "vcpu": 8,
        "memory_gib": 32,
        "disk_gib": 500,
        "idle": False,
    },
    {
        "vm_name": "legacy-app-01",
        "namespace": "legacy",
        "node_name": "worker-1",
        "guest_os": "linux",
        "guest_agent": False,
        "vcpu": 2,
        "memory_gib": 4,
        "disk_gib": 50,
        "idle": False,
    },
    {
        "vm_name": "idle-vm-01",
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


def _gib_to_kib(memory_gib):
    """Convert gibibytes to kibibytes."""
    return int(memory_gib * KIB_PER_GIB)


def _is_business_hour(timestamp):
    """Return True during typical business hours (08:00-17:59 UTC)."""
    return 8 <= timestamp.hour < 18


def _day_offset(start_date, interval_start):
    """Whole-day offset from generator start for slow-changing metrics."""
    return max(0, (interval_start.date() - start_date.date()).days)


class OCPVirtualMachineGenerator(AbstractGenerator):
    """Generates ros-openshift-vm-usage style CSV data for ros-ocp-backend."""

    def __init__(
        self, start_date, end_date, attributes, ros_ocp_info=False, constant_values_ros_ocp=False, ros_only=False
    ):
        """Initialize the VM ROS generator."""
        del ros_ocp_info, constant_values_ros_ocp, ros_only
        self._attributes = attributes or {}
        self._vms = self._load_vms()
        self._filesystem_used_bytes = {}
        super().__init__(start_date, end_date, hour_delta=datetime.timedelta(minutes=59, seconds=59))
        self.ocp_report_generation = {
            OCP_ROS_VM_USAGE: {
                "_generate_hourly_data": self._gen_quarter_hourly_vm_usage,
                "_update_data": self._update_vm_ros_data,
            },
        }

    def _load_vms(self):
        """Load VM definitions from static YAML attributes."""
        vms = self._attributes.get("vms")
        if not vms:
            return [dict(vm) for vm in DEFAULT_VMS]
        loaded = []
        for item in vms:
            vm = dict(item)
            vm.setdefault("guest_agent", True)
            vm.setdefault("idle", False)
            vm.setdefault("abandoned", False)
            vm.setdefault("guest_os", "linux")
            loaded.append(vm)
        return loaded

    def _init_data_row(self, start, end, **kwargs):
        """Create a row with placeholders for all VM ROS headers."""
        del start, end
        report_type = kwargs.get(REPORT_TYPE)
        del report_type
        return {column: "" for column in OCP_ROS_VM_COLUMNS}

    def _add_common_usage_info(self, row, start, end, **kwargs):
        """Add interval timestamps."""
        del kwargs
        row["interval_start"] = OCPGenerator.timestamp(start)
        row["interval_end"] = OCPGenerator.timestamp(end)
        return row

    def _update_data(self, row, start, end, **kwargs):
        """Populate a single 15-minute VM usage row (AbstractGenerator contract)."""
        return self._update_vm_ros_data(row, start, end, **kwargs)

    def _update_vm_ros_data(self, row, start, end, **kwargs):
        """Populate a single 15-minute VM usage row."""
        del end
        vm = kwargs.get("vm")
        row.update(self._build_vm_metrics(vm, start))
        return row

    def _build_vm_metrics(self, vm, interval_start):
        """Compute metric values for one VM at one interval."""
        vcpu = int(vm.get("vcpu", 2))
        memory_gib = float(vm.get("memory_gib", 4))
        disk_gib = float(vm.get("disk_gib", 50))
        guest_agent = bool(vm.get("guest_agent", True))
        abandoned = bool(vm.get("abandoned", False))
        idle = bool(vm.get("idle", False))
        guest_os = str(vm.get("guest_os", "linux")).lower()

        cpu_request_mc = vcpu * 1000
        cpu_limit_mc = vcpu * 1000
        memory_request_kib = _gib_to_kib(memory_gib)
        disk_allocated_bytes = int(disk_gib * GIGABYTE)

        if abandoned:
            cpu_usage_mc = 0
            memory_usage_kib = 0
        elif idle:
            cpu_usage_mc = randint(5, 45)
            idle_cap = IDLE_WINDOWS_MEMORY_KIB if guest_os == "windows" else IDLE_LINUX_MEMORY_KIB
            memory_usage_kib = randint(max(1, idle_cap // 4), idle_cap)
        elif _is_business_hour(interval_start):
            cpu_usage_mc = int(cpu_request_mc * uniform(0.20, 0.80))
            memory_usage_kib = int(memory_request_kib * uniform(0.50, 0.85))
        else:
            cpu_usage_mc = int(cpu_request_mc * uniform(0.05, 0.15))
            memory_usage_kib = int(memory_request_kib * uniform(0.50, 0.85))

        cpu_usage_mc = max(0, min(cpu_usage_mc, cpu_limit_mc))

        row = {
            "vm_name": vm.get("vm_name", ""),
            "namespace": vm.get("namespace", ""),
            "node_name": vm.get("node_name", ""),
            "guest_os": guest_os,
            "cpu_usage_mc": cpu_usage_mc,
            "cpu_request_mc": cpu_request_mc,
            "cpu_limit_mc": cpu_limit_mc,
            "memory_usage_kib": memory_usage_kib,
            "memory_request_kib": memory_request_kib,
            "disk_allocated_bytes": disk_allocated_bytes,
            "disk_read_iops": 0 if abandoned else randint(100, 2000),
            "disk_write_iops": 0 if abandoned else randint(50, 1000),
            "disk_read_bytes_per_sec": 0 if abandoned else randint(1024, 512000),
            "disk_write_bytes_per_sec": 0 if abandoned else randint(512, 256000),
        }

        if guest_agent:
            buffer_kib = int(memory_request_kib * uniform(0.02, 0.10))
            row["memory_available_kib"] = max(0, memory_request_kib - memory_usage_kib + buffer_kib)
            row["filesystem_capacity_bytes"] = disk_allocated_bytes
            vm_key = vm.get("vm_name", "")
            if vm_key not in self._filesystem_used_bytes:
                self._filesystem_used_bytes[vm_key] = int(uniform(5, 20) * GIGABYTE)
            day_index = _day_offset(self.start_date, interval_start)
            daily_growth = uniform(0.1, 0.5) * GIGABYTE
            row["filesystem_used_bytes"] = min(
                disk_allocated_bytes,
                int(self._filesystem_used_bytes[vm_key] + day_index * daily_growth),
            )
        else:
            row["memory_available_kib"] = ""
            row["filesystem_used_bytes"] = ""
            row["filesystem_capacity_bytes"] = ""

        return row

    def _gen_quarter_hourly_vm_usage(self, **kwargs):
        """Create 15-minute interval data for each configured VM."""
        for quarter_hour in self.quarter_hours:
            start = quarter_hour.get("start")
            end = quarter_hour.get("end")
            for vm in self._vms:
                row = self._init_data_row(start, end, **kwargs)
                row = self._add_common_usage_info(row, start, end, **kwargs)
                yield self._update_vm_ros_data(row, start, end, vm=vm, **kwargs)

    def _generate_hourly_data(self, **kwargs):
        """Dispatch to the configured report generator method."""
        report_type = kwargs.get(REPORT_TYPE)
        method = self.ocp_report_generation.get(report_type).get("_generate_hourly_data")
        return method(**kwargs)

    def generate_data(self, report_type=None):
        """Generate VM ROS usage rows for the requested report type."""
        meta = {REPORT_TYPE: report_type}
        return self._generate_hourly_data(**meta)
