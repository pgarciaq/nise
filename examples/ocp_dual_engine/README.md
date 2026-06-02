# Dual-engine OCP fixture

`ocp_static_data.yml` defines two container workloads on one node:

| Pod | Pattern | Expected engine behavior |
|-----|---------|--------------------------|
| `spike-cpu-api` | Low `cpu_usage` vs high `cpu_request` | Cost CPU recommendation lower than performance |
| `steady-mem-worker` | Stable `mem_usage_gig` | Similar memory sizing across engines |

After ingestion, compare:

```http
GET /api/cost-management/v1/recommendations/openshift?filter[container]=spike-cpu-api&filter[engine]=cost
GET /api/cost-management/v1/recommendations/openshift?filter[container]=spike-cpu-api&filter[engine]=performance
```

Performance CPU requests should be greater than or equal to cost for the spiky workload.
