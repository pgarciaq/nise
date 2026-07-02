# ROS OCP E2E Test Templates

These nise YAML templates generate scenario-specific OCP data for testing
the ros-ocp-backend native engine features. Each template targets a specific
feature area (GPU MIG, VM placement, PVC rightsizing, etc.).

## Usage

```bash
nise report ocp --static-report-file examples/ros_ocp_e2e/ocp_report_gpu_mig.yml \
  --ocp-cluster-id my-cluster --write-monthly --ros-ocp-info
```

## Templates by Feature Area

### GPU
- `ocp_report_gpu_mig.yml` — GPU MIG profile recommendations
- `ocp_report_gpu_mig_ros.yml` — GPU MIG with ROS container data
- `ocp_report_gpu_timeslicing.yml` — GPU time-slicing recommendations
- `ocp_report_gpu_combined.yml` — Combined GPU scenarios

### Virtual Machines
- `ocp_report_vm.yml` — Basic VM workloads
- `ocp_report_vm_enhancements.yml` — VM sizing enhancements (notifications 46–49)
- `ocp_report_vm_enhancements_64_69.yml` — Extended VM enhancement scenarios
- `ocp_report_vm_gpu.yml` — VMs with GPU
- `ocp_report_vm_gpu_timeslicing.yml` — VMs with GPU time-slicing
- `ocp_report_vm_io_profiling.yml` — VM disk I/O profiling
- `ocp_report_vm_network.yml` — VM network metrics
- `ocp_report_vm_notifications.yml` — VM notification scenarios
- `ocp_report_vm_placement.yml` — VM placement recommendations
- `ocp_report_vm_mvp_promotions.yml` — VM MVP promotion scenarios

### Storage
- `ocp_report_pvc_rightsizing.yml` — PVC rightsizing recommendations
- `ocp_report_snapshot_classification.yml` — Snapshot staleness classification

### Quotas
- `ocp_report_cluster_quota.yml` — Cluster resource quota recommendations
- `ocp_report_quota.yml` — Namespace quota recommendations

### Nodes
- `ocp_report_node_idle_consolidation.yml` — Node idle detection and consolidation

### Containers
- `ocp_report_business_hours.yml` — Business hours vs all-hours comparison
- `ocp_report_ros_0.yml` — Basic ROS container data
- `ocp_report_advanced.yml` / `ocp_report_advanced_daily.yml` — Advanced scenarios

### Other
- `ocp_report_0_template.yml` — Basic template
- `ocp_report_daily_flow_template.yml` — Daily ingestion flow
- `ocp_report_distro.yml` — Distribution scenarios
- `ocp_report_forecast_const.yml` / `ocp_report_forecast_outlier.yml` — Forecasting
- `ocp_ai_workloads_template.yml` — AI/ML workloads
- `ocp_report_missing_items.yml` — Missing data handling
- `ocp_random_cpu_for_eap_report.yml` — Random CPU patterns for EAP
- `today_ocp_report_*.yml` — Templates generating data for today's date

## Template Format

Templates use nise YAML format with date placeholders:
- `start_date: last_month` — Replaced with calculated start date
- `start_date: today` — Replaced with test run date

The test framework automatically substitutes these placeholders with actual dates.

## Consumed by

- `cost-onprem-chart/tests/` E2E test suite
- Manual testing during feature development
