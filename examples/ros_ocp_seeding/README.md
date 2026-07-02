# ROS OCP Data Seeding Templates

These nise YAML templates are used by the cost-onprem-chart E2E test framework's
automatic data seeding fixture. They generate minimum baseline data to ensure
recommendation tables meet threshold row counts before tests run.

## Templates

| File | Purpose | Target Table |
|------|---------|--------------|
| `seed_container.yml` | Container CPU/memory workloads | `daily_container_digests` |
| `seed_pvc.yml` | PVC storage workloads | `daily_pvc_digests` |
| `seed_gpu.yml` | GPU workloads (MIG + time-slicing) | `gpu_container_digests` |
| `seed_cluster_quota.yml` | Cluster resource quotas | `cluster_quota_recommendation_sets` |
| `seed_domain.yml` | Domain/workload type classification | `daily_container_digests` |

## Usage

These are typically consumed by `data_seeding.py` (session-scoped pytest fixture),
not run manually. But you can use them directly:

```bash
nise report ocp --static-report-file examples/ros_ocp_seeding/seed_container.yml \
  --ocp-cluster-id my-cluster --write-monthly --ros-ocp-info
```

## Thresholds

The auto-seeding fixture checks these minimum row counts and only seeds
categories that fall below their threshold:

| Category | Minimum Rows |
|----------|-------------|
| container | 100 |
| namespace | 50 |
| PVC | 20 |
| GPU | 20 |
| cluster_quota | 2 |
| business_hours | 30 |
