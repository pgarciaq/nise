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
from nise.generators.ocp.ocp_generator import OCP_ROS_VM_GPU_DEVICE
from nise.generators.ocp.ocp_generator import OCP_ROS_VM_GPU_DEVICE_COLUMNS
from nise.generators.ocp.ocp_generator import OCP_ROS_VM_PVC
from nise.generators.ocp.ocp_generator import OCP_ROS_VM_PVC_COLUMNS
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
            OCP_ROS_VM_GPU_DEVICE: {
                "_generate_hourly_data": self._gen_quarter_hourly_vm_gpu_device,
                "_update_data": self._update_vm_gpu_device_data,
            },
            OCP_ROS_VM_PVC: {
                "_generate_hourly_data": self._gen_quarter_hourly_vm_pvc,
                "_update_data": self._update_vm_pvc_data,
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
            if "guest_os" not in vm:
                vm["guest_os"] = "linux"
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

    def _compute_cpu_mem_usage(self, vm, interval_start):  # noqa: C901
        """Determine CPU (millicores) and memory (KiB) usage for a VM scenario."""
        vcpu = int(vm.get("vcpu", 2))
        memory_gib = float(vm.get("memory_gib", 4))
        guest_os = str(vm.get("guest_os", "linux")).lower()

        cpu_request_mc = vcpu * 1000
        memory_request_kib = _gib_to_kib(memory_gib)

        if bool(vm.get("abandoned", False)):
            return 0, 0

        if bool(vm.get("idle", False)):
            idle_cap = IDLE_WINDOWS_MEMORY_KIB if guest_os == "windows" else IDLE_LINUX_MEMORY_KIB
            return randint(5, 45), randint(max(1, idle_cap // 4), idle_cap)

        if vm.get("cpu_pattern") == "variable":
            swing = uniform(0.05, 0.95)
            return int(cpu_request_mc * swing), int(memory_request_kib * uniform(0.40, 0.85))

        fixed_usage = vm.get("fixed_usage")
        if fixed_usage and isinstance(fixed_usage, dict):
            cpu = int(cpu_request_mc * float(fixed_usage.get("cpu_pct", 0.40)))
            mem = int(memory_request_kib * float(fixed_usage.get("mem_pct", 0.65)))
            return cpu, mem

        day_index = _day_offset(self.start_date, interval_start)
        total_days = max(1, (self.end_date.date() - self.start_date.date()).days)

        if bool(vm.get("oversized_for_instance_type", False)):
            return int(cpu_request_mc * 0.20), int(memory_request_kib * 0.35)

        if bool(vm.get("power_off_candidate", False)):
            # Mostly idle days with occasional business-hour activity (notification 64).
            day_index = _day_offset(self.start_date, interval_start)
            if day_index % 4 == 0 and _is_business_hour(interval_start):
                return int(cpu_request_mc * uniform(0.35, 0.55)), int(memory_request_kib * uniform(0.45, 0.65))
            idle_cap = IDLE_WINDOWS_MEMORY_KIB if guest_os == "windows" else IDLE_LINUX_MEMORY_KIB
            return randint(5, 40), randint(max(1, idle_cap // 4), idle_cap)

        if bool(vm.get("downsize_unstable", False)) and _is_business_hour(interval_start):
            if day_index >= total_days - 1:
                return int(cpu_request_mc * 0.90), int(memory_request_kib * 0.80)
            return int(cpu_request_mc * 0.15), int(memory_request_kib * 0.55)

        if bool(vm.get("windows_update_spike", False)) and guest_os == "windows" and _is_business_hour(interval_start):
            if interval_start.hour % 2 == 0:
                return int(cpu_request_mc * 0.95), int(memory_request_kib * 0.85)
            return int(cpu_request_mc * 0.35), int(memory_request_kib * 0.60)

        if _is_business_hour(interval_start):
            return int(cpu_request_mc * uniform(0.20, 0.80)), int(memory_request_kib * uniform(0.50, 0.85))

        return int(cpu_request_mc * uniform(0.05, 0.15)), int(memory_request_kib * uniform(0.50, 0.85))

    def _compute_disk_io(self, vm, abandoned):
        """Return disk I/O metrics for one VM (IOPS and bytes/sec)."""
        if abandoned:
            return 0, 0, 0, 0
        read_iops = randint(100, 2000)
        write_iops = randint(50, 1000)
        read_bps = randint(1024, 512000)
        write_bps = randint(512, 256000)
        if bool(vm.get("high_io", False)):
            read_iops = 6000
            write_iops = 6000
            read_bps = 2_000_000
            write_bps = 1_000_000
        elif bool(vm.get("sequential_io", False)):
            read_iops = 800
            write_iops = 400
            read_bps = read_iops * 131072
            write_bps = write_iops * 131072
        elif bool(vm.get("random_io", False)):
            # Peak IOPS > 5000 for ROS storage-tier notification 68 (random high IOPS).
            read_iops = 3000
            write_iops = 2500
            read_bps = read_iops * 4096
            write_bps = write_iops * 4096
        elif bool(vm.get("low_io", False)):
            read_iops = 20
            write_iops = 10
            read_bps = 8192
            write_bps = 4096
        return read_iops, write_iops, read_bps, write_bps

    def _build_vm_metrics(self, vm, interval_start):  # noqa: C901
        """Compute metric values for one VM at one interval."""
        vcpu = int(vm.get("vcpu", 2))
        memory_gib = float(vm.get("memory_gib", 4))
        disk_gib = float(vm.get("disk_gib", 50))
        abandoned = bool(vm.get("abandoned", False))
        crash_loop = bool(vm.get("crash_loop", False))
        guest_os = str(vm.get("guest_os", "linux")).lower() if "guest_os" in vm else "linux"

        cpu_request_mc = vcpu * 1000
        cpu_limit_mc = vcpu * 1000
        memory_request_kib = _gib_to_kib(memory_gib)
        disk_allocated_bytes = int(disk_gib * GIGABYTE)
        day_index = _day_offset(self.start_date, interval_start)
        if bool(vm.get("disk_growing_hypervisor", False)):
            disk_allocated_bytes = int((100 + day_index * 6) * GIGABYTE)

        cpu_usage_mc, memory_usage_kib = self._compute_cpu_mem_usage(vm, interval_start)

        cpu_usage_mc = max(0, min(cpu_usage_mc, cpu_limit_mc))

        read_iops, write_iops, read_bps, write_bps = self._compute_disk_io(vm, abandoned)

        net_rx_bps = net_tx_bps = net_rx_pps = net_tx_pps = net_rx_drops = net_tx_drops = 0.0
        if bool(vm.get("network_heavy", False)) and not abandoned:
            # ~500 Mbps aggregate with moderate CPU/memory (n1 classification tests).
            net_rx_bps = 31_250_000
            net_tx_bps = 31_250_000
            net_rx_pps = 55_000
            net_tx_pps = 55_000
            net_rx_drops = 80
            net_tx_drops = 40
            if bool(vm.get("network_qos_sriov", False)):
                # Sustained multi-Gbps + drops (notifications 65).
                net_rx_bps = 3_000_000_000
                net_tx_bps = 3_000_000_000
                net_rx_drops = 12_000
                net_tx_drops = 8_000
            if bool(vm.get("network_qos_dpdk", False)):
                # High PPS, small average packet size (notification 66).
                net_rx_pps = 600_000
                net_tx_pps = 600_000
                net_rx_bps = net_rx_pps * 128
                net_tx_bps = net_tx_pps * 128

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
            "disk_read_iops": read_iops,
            "disk_write_iops": write_iops,
            "disk_read_bytes_per_sec": read_bps,
            "disk_write_bytes_per_sec": write_bps,
            "restart_count": 0,
        }

        if crash_loop and not abandoned:
            row["restart_count"] = randint(1, 3)

        if self._guest_agent_active(vm, interval_start):
            buffer_kib = int(memory_request_kib * uniform(0.02, 0.10))
            row["memory_available_kib"] = max(0, memory_request_kib - memory_usage_kib + buffer_kib)
            row["filesystem_capacity_bytes"] = disk_allocated_bytes
            vm_key = vm.get("vm_name", "")
            if vm_key not in self._filesystem_used_bytes:
                base_used = (
                    8 * GIGABYTE if bool(vm.get("disk_filling_guest", False)) else int(uniform(5, 20) * GIGABYTE)
                )
                self._filesystem_used_bytes[vm_key] = base_used
            if bool(vm.get("disk_critical", False)):
                row["filesystem_used_bytes"] = int(disk_allocated_bytes * 0.96)
            else:
                daily_growth = (
                    6 * GIGABYTE if bool(vm.get("disk_filling_guest", False)) else uniform(0.1, 0.5) * GIGABYTE
                )
                row["filesystem_used_bytes"] = min(
                    disk_allocated_bytes,
                    int(self._filesystem_used_bytes[vm_key] + day_index * daily_growth),
                )
        else:
            row["memory_available_kib"] = ""
            row["filesystem_used_bytes"] = ""
            row["filesystem_capacity_bytes"] = ""

        gpu_count = int(vm.get("gpu_count", 0) or 0)
        if gpu_count > 0:
            row.update(self._gpu_metrics(vm))

        if net_rx_bps > 0 or net_tx_bps > 0:
            row["net_rx_bytes_per_sec"] = net_rx_bps
            row["net_tx_bytes_per_sec"] = net_tx_bps
            row["net_rx_packets_per_sec"] = net_rx_pps
            row["net_tx_packets_per_sec"] = net_tx_pps
            row["net_rx_drops_per_sec"] = net_rx_drops
            row["net_tx_drops_per_sec"] = net_tx_drops

        return row

    def _gpu_utilization_values(self, scenario):
        """Return DCGM-style utilization ratios for a named GPU scenario."""
        levels = {
            "idle": (0.01, 0.02, 0.01, 0.01, 0.01, 512),
            "low": (0.08, 0.12, 0.10, 0.08, 0.06, 4096),
            "medium": (0.45, 0.55, 0.40, 0.35, 0.30, 16384),
            "high": (0.72, 0.80, 0.65, 0.55, 0.45, 32768),
            "saturated": (0.92, 0.98, 0.88, 0.82, 0.75, 72000),
            # Low SM/DRAM with frame-buffer >80% of T4 VRAM (notification 57).
            "fb_saturated": (0.25, 0.28, 0.22, 0.20, 0.18, 15000),
        }
        return levels.get(str(scenario).lower(), levels["medium"])

    def _gpu_metrics(self, vm):
        """Populate GPU columns for VMs with gpu_count > 0."""
        gpu_count = int(vm.get("gpu_count", 0) or 0)
        scenario = vm.get("gpu_utilization", "medium")
        util_avg, util_max, sm_avg, tensor_avg, dram_avg, fb_max = self._gpu_utilization_values(scenario)
        return {
            "gpu_count": gpu_count,
            "gpu_model": vm.get("gpu_model", "NVIDIA T4"),
            "gpu_utilization_avg": util_avg,
            "gpu_utilization_max": util_max,
            "gpu_fb_used_avg_mib": fb_max * 0.6,
            "gpu_fb_used_max_mib": fb_max,
            "gpu_sm_active_avg": sm_avg,
            "gpu_tensor_active_avg": tensor_avg,
            "gpu_dram_active_avg": dram_avg,
            "gpu_mig_profile": vm.get("gpu_mig_profile", ""),
            "gpu_max_slices": 7 if vm.get("gpu_mig_profile") else 0,
        }

    def _guest_agent_active(self, vm, interval_start):
        """Return True when guest-agent columns should be populated for this interval."""
        remove_day = vm.get("agent_remove_day")
        if remove_day is not None:
            return _day_offset(self.start_date, interval_start) < int(remove_day)

        if not bool(vm.get("guest_agent", True)):
            return False

        install_hour = vm.get("agent_install_hour")
        if install_hour is not None:
            elapsed_hours = (interval_start - self.start_date).total_seconds() / 3600.0
            return elapsed_hours >= float(install_hour)
        return True

    def _init_gpu_device_row(self, start, end, **kwargs):
        del start, end, kwargs
        return {column: "" for column in OCP_ROS_VM_GPU_DEVICE_COLUMNS}

    def _update_vm_gpu_device_data(self, row, start, end, **kwargs):
        del end
        vm = kwargs.get("vm")
        device = kwargs.get("gpu_device")
        row["interval_start"] = OCPGenerator.timestamp(start)
        row["namespace"] = vm.get("namespace", "")
        row["vm_name"] = vm.get("vm_name", "")
        row["gpu_uuid"] = device.get("uuid", "")
        row["gpu_model"] = device.get("model", vm.get("gpu_model", ""))
        scenario = device.get("utilization", vm.get("gpu_utilization", "medium"))
        util_avg, util_max, sm_avg, tensor_avg, dram_avg, fb_max = self._gpu_utilization_values(scenario)
        row["utilization_avg"] = util_avg
        row["utilization_max"] = util_max
        row["fb_used_avg_mib"] = fb_max * 0.6
        row["fb_used_max_mib"] = fb_max
        row["sm_active_avg"] = sm_avg
        row["tensor_active_avg"] = tensor_avg
        row["dram_active_avg"] = dram_avg
        row["mig_profile"] = device.get("mig_profile", vm.get("gpu_mig_profile", ""))
        row["max_slices"] = 7 if row["mig_profile"] else 0
        return row

    def _gen_quarter_hourly_vm_gpu_device(self, **kwargs):
        """Emit one row per GPU device per 15-minute interval."""
        for quarter_hour in self.quarter_hours:
            start = quarter_hour.get("start")
            end = quarter_hour.get("end")
            for vm in self._vms:
                devices = vm.get("gpu_devices")
                if devices:
                    for device in devices:
                        row = self._init_gpu_device_row(start, end, **kwargs)
                        yield self._update_vm_gpu_device_data(row, start, end, vm=vm, gpu_device=device, **kwargs)
                    continue
                gpu_count = int(vm.get("gpu_count", 0) or 0)
                if gpu_count <= 0:
                    continue
                for idx in range(gpu_count):
                    device = {
                        "uuid": f"GPU-{vm.get('vm_name', 'vm')}-{idx}",
                        "model": vm.get("gpu_model", "NVIDIA T4"),
                        "utilization": vm.get("gpu_utilization", "medium"),
                        "mig_profile": vm.get("gpu_mig_profile", ""),
                    }
                    row = self._init_gpu_device_row(start, end, **kwargs)
                    yield self._update_vm_gpu_device_data(row, start, end, vm=vm, gpu_device=device, **kwargs)

    def _gen_quarter_hourly_vm_usage(self, **kwargs):
        """Create 15-minute interval data for each configured VM."""
        for quarter_hour in self.quarter_hours:
            start = quarter_hour.get("start")
            end = quarter_hour.get("end")
            for vm in self._vms:
                row = self._init_data_row(start, end, **kwargs)
                row = self._add_common_usage_info(row, start, end, **kwargs)
                yield self._update_vm_ros_data(row, start, end, vm=vm, **kwargs)

    def _init_pvc_row(self, start, end, **kwargs):
        del start, end, kwargs
        return {column: "" for column in OCP_ROS_VM_PVC_COLUMNS}

    def _update_vm_pvc_data(self, row, start, end, **kwargs):
        """Populate a single PVC attachment row."""
        del end
        vm = kwargs.get("vm")
        pvc_device = kwargs.get("pvc_device")
        row["interval_start"] = OCPGenerator.timestamp(start)
        row["interval_end"] = OCPGenerator.timestamp(start + datetime.timedelta(minutes=15))
        row["vm_name"] = vm.get("vm_name", "")
        row["namespace"] = vm.get("namespace", "")
        row["node_name"] = vm.get("node_name", "")
        row["pvc_name"] = pvc_device.get("name", "")
        capacity_gib = float(pvc_device.get("capacity_gib", 50))
        row["disk_capacity_bytes"] = int(capacity_gib * GIGABYTE)
        row["volume_mode"] = pvc_device.get("volume_mode", "Filesystem")
        return row

    def _gen_quarter_hourly_vm_pvc(self, **kwargs):
        """Emit one row per PVC device per 15-minute interval."""
        for quarter_hour in self.quarter_hours:
            start = quarter_hour.get("start")
            end = quarter_hour.get("end")
            for vm in self._vms:
                pvc_devices = vm.get("pvc_devices")
                if not pvc_devices:
                    continue
                for pvc_device in pvc_devices:
                    row = self._init_pvc_row(start, end, **kwargs)
                    yield self._update_vm_pvc_data(row, start, end, vm=vm, pvc_device=pvc_device, **kwargs)

    def _generate_hourly_data(self, **kwargs):
        """Dispatch to the configured report generator method."""
        report_type = kwargs.get(REPORT_TYPE)
        method = self.ocp_report_generation.get(report_type).get("_generate_hourly_data")
        return method(**kwargs)

    def generate_data(self, report_type=None):
        """Generate VM ROS usage rows for the requested report type."""
        meta = {REPORT_TYPE: report_type}
        return self._generate_hourly_data(**meta)
