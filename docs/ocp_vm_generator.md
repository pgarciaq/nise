# OpenShift Virtualization (VM) ROS data generator

`OCPVirtualMachineGenerator` produces **`ocp_ros_vm_usage.csv`** at **15-minute** intervals for
[ros-ocp-backend](https://github.com/project-koku/ros-ocp-backend) VM recommendations. Use it with
`nise report ocp` and **`--ros-ocp-info`** (required for the ROS CSV).

## Quick start

```bash
nise report ocp \
  --static-report-file examples/ocp_vm/vm_static_data.yml \
  --ocp-cluster-id <CLUSTER-UUID> \
  --ros-ocp-info \
  -s 2026-05-01 -e 2026-05-03 -w
```

VM-only output (no pod/cost reports): omit `--ros-ocp-info` and use the same static file; only
`OCPVirtualMachineGenerator` runs when it is the sole generator in the YAML.

Package `ocp_ros_vm_usage.csv` in the upload manifest (not combined `openshift_report` files).
See [ros-ocp-backend VM design](https://github.com/project-koku/ros-ocp-backend/blob/main/docs/design/vm-recommendations.md).

## YAML structure

```yaml
generators:
  - OCPVirtualMachineGenerator:
      start_date: YYYY-MM-DD
      end_date: YYYY-MM-DD
      vms:
        - vm_name: my-vm
          namespace: production
          # ... per-VM parameters below
```

## Per-VM parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `vm_name` | string | yes | VM name (KubeVirt `name` label). |
| `namespace` | string | yes | Kubernetes namespace. |
| `node_name` | string | yes | Node hosting the VMI. |
| `guest_os` | string | yes | `linux`, `windows`, or `""` (empty = unknown OS; ROS notification **46**). |
| `guest_agent` | bool | yes | `true` if QEMU guest agent columns are populated; `false` leaves them empty. |
| `vcpu` | int | yes | Requested vCPU count. |
| `memory_gib` | int | yes | Requested memory (GiB). |
| `disk_gib` | int | yes | Allocated disk size (GiB). |
| `idle` | bool | no | Both CPU and memory usage stay below idle thresholds (ROS notification **18**). |
| `abandoned` | bool | no | Zero CPU and memory max every day (ROS notification **43**). |
| `crash_loop` | bool | no | Elevated `restart_count` per interval (ROS notification **48**). |
| `windows_update_spike` | bool | no | Windows-only P99≫P95 spread (ROS notification **47**). |
| `downsize_unstable` | bool | no | Performance engine holds downsize (ROS notification **49**). |
| `fixed_usage` | dict | no | Steady usage: `cpu_pct` and `mem_pct` (0.0–1.0 of request). Used for kernel-reserve comparison pairs. |
| `agent_install_hour` | int | no | Guest agent appears this many hours after `start_date` (late install). |
| `agent_remove_day` | int | no | Guest agent stops after this day offset from `start_date` (removal scenario). |
| `gpu_count` | int | no | Number of GPUs attached (0 = no GPU columns). When &gt; 0, DCGM-style GPU columns are emitted (31 CSV fields total). |
| `gpu_model` | string | no | GPU product name (e.g. `NVIDIA A100-SXM4-80GB`, `NVIDIA T4`). Default `NVIDIA T4`. |
| `gpu_utilization` | string | no | Utilization scenario: `idle`, `low`, `medium`, `high`, `saturated` (maps to SM/tensor/FB metrics). |
| `gpu_mig_profile` | string | no | MIG profile label (e.g. `3g.20gb`); sets `gpu_max_slices` when present. |
| `gpu_devices` | list | no | Per-GPU configs when `gpu_count` alone is not enough (multi-GPU mixed utilization). Each entry: `uuid`, `model`, `utilization`, optional `mig_profile`. |
| `cpu_pattern` | string | no | `variable` — CPU usage swings between ~5% and ~95% of request each interval (adaptive margin testing). |

### Per-GPU device CSV (`ocp_ros_vm_gpu_device`)

When a VM has `gpu_devices` or `gpu_count` &gt; 0, nise also emits **`ocp_ros_vm_gpu_device.csv`** (15-minute rows, one per device per interval).

| Column | Description |
|--------|-------------|
| `interval_start` | Interval timestamp |
| `namespace`, `vm_name` | VM identity |
| `gpu_uuid`, `gpu_model` | Device identity |
| `utilization_avg`, `utilization_max` | Utilization ratios (from `utilization` scenario per device) |
| `fb_used_avg_mib`, `fb_used_max_mib` | Frame buffer used (MiB) |
| `sm_active_avg`, `tensor_active_avg`, `dram_active_avg` | Activity ratios |
| `mig_profile`, `max_slices` | MIG profile when set |

VMs without GPUs produce **no** device CSV rows. With `gpu_devices`, only those devices are emitted; otherwise nise synthesizes one row per `gpu_count` using the VM-level `gpu_model` / `gpu_utilization`.

### GPU utilization scenarios

| `gpu_utilization` | ROS classification (typical) | Notification |
|-------------------|-------------------------------|--------------|
| `idle` | `idle` | **50** |
| `low` | `underutilized` | **51** |
| `medium` | `well_utilized` | — |
| `high` | varies | — |
| `saturated` | `memory_saturated` on smaller GPUs (e.g. T4) or `compute_saturated` on large GPUs (e.g. A100) | **52** or **53** |

Use a smaller `gpu_model` (T4) with `saturated` to exercise frame-buffer saturation (**52**); use A100 with `saturated` for compute saturation (**53**).

## Example scenarios

See [`examples/ocp_vm/vm_static_data.yml`](../examples/ocp_vm/vm_static_data.yml) for:

- Active Linux/Windows with guest agent
- Idle and abandoned VMs
- Late agent install and agent removal
- Crash loop, Windows update spike, unstable downsize, unknown OS
- Windows vs Linux fixed-usage pair (kernel reserve testing)
- GPU idle, underutilized MIG, memory/compute saturated, well-utilized (`gpu_count`, `gpu_utilization`)
- **Multi-GPU mixed** (`multi-gpu-mixed-vm`) — `gpu_devices` with one idle and one active GPU (notification **54**)
- **Variable CPU** (`variable-cpu-vm`) — `cpu_pattern: variable` for adaptive margin tests

```yaml
        - vm_name: multi-gpu-mixed-vm
          namespace: ml-training
          guest_os: linux
          guest_agent: true
          vcpu: 16
          memory_gib: 64
          disk_gib: 500
          gpu_count: 2
          gpu_devices:
            - uuid: "GPU-aaa-111"
              model: "NVIDIA A100-SXM4-80GB"
              utilization: high
            - uuid: "GPU-bbb-222"
              model: "NVIDIA A100-SXM4-80GB"
              utilization: idle
        - vm_name: variable-cpu-vm
          namespace: batch-jobs
          guest_os: linux
          guest_agent: true
          vcpu: 4
          memory_gib: 8
          disk_gib: 100
          cpu_pattern: variable
```

IQE and cost-onprem E2E use `iqe_cost_management/data/openshift/ocp_report_ros_vm.yml`,
`cost-onprem-chart/tests/data/nise_templates/ocp_report_vm_enhancements.yml`, and
`cost-onprem-chart/tests/data/nise_templates/ocp_report_vm_gpu.yml` with the same parameters.
