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

## Example scenarios

See [`examples/ocp_vm/vm_static_data.yml`](../examples/ocp_vm/vm_static_data.yml) for:

- Active Linux/Windows with guest agent
- Idle and abandoned VMs
- Late agent install and agent removal
- Crash loop, Windows update spike, unstable downsize, unknown OS
- Windows vs Linux fixed-usage pair (kernel reserve testing)

IQE and cost-onprem E2E use `iqe_cost_management/data/openshift/ocp_report_ros_vm.yml` and
`cost-onprem-chart/tests/data/nise_templates/ocp_report_vm_enhancements.yml` with the same parameters.
