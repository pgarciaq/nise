#!/usr/bin/env python3
"""Post-process nise-generated ROS CSVs to produce realistic usage patterns.

Nise generates random container names with usage drawn from a wide uniform
distribution that often far exceeds requests, making every recommendation
say "increase dramatically."  This script replaces the usage columns with
values that create a realistic mix of recommendation scenarios:

  CPU/Memory scenarios (all containers):
  - Over-provisioned  (40%): usage ~30-50% of request  → "decrease request"
  - Under-provisioned (30%): usage ~120-200% of request → "increase request"
  - Well-sized        (20%): usage ~70-95% of request   → minor / no change
  - Memory-pressure   (10%): normal CPU, memory near limit, OOM events

  GPU scenarios (containers that have a non-empty accelerator_model_name):
  - idle              (15%): SM < 0.02  → recommend "remove GPU"
  - underutilized     (25%): SM < 0.25, Tensor < 0.15 → recommend MIG or smaller
  - memory_bound      (10%): DRAM > 0.60, Tensor < 0.15 → memory-heavy workload
  - well_utilized     (50%): all metrics healthy → no change

  Tier 2 GPUs (models without profiling data, e.g. V100, P100) always
  receive the "no_profiling" scenario — only frame-buffer usage is set.

Usage:
  python3 postprocess_ros_csvs.py INPUT_DIR OUTPUT_DIR CLUSTER_UUID

  INPUT_DIR     Directory containing nise *-ocp_ros_usage-*.csv files
  OUTPUT_DIR    Where to write post-processed CSVs (plus copies of non-ROS files)
  CLUSTER_UUID  The cluster UUID used with nise --ocp-cluster-id

Non-ROS CSV files (pod_usage, storage, node_label, etc.) are copied
unchanged so OUTPUT_DIR contains everything needed for the tarball.
"""

import csv
import glob
import hashlib
import os
import random
import shutil
import sys

GIB = 1024**3
MIB = 1024**2

# GPU models that support DCGM profiling metrics (Turing+).
# Must stay in sync with GPU_PROFILING_SUPPORTED in ocp_generator.py.
TIER1_GPU_MODELS = {"T4", "A10", "A30", "A100", "L4", "L40", "L40S", "H100", "H200", "B100", "B200"}

# Frame-buffer capacity per model (MiB).  Used for realistic FB usage ranges.
GPU_FB_CAPACITY = {
    "T4": 15360,
    "A10": 24576,
    "A30": 24576,
    "A100": 81920,
    "L4": 24576,
    "L40": 49152,
    "L40S": 49152,
    "H100": 81920,
    "H200": 143360,
    "B100": 196608,
    "B200": 196608,
    "V100": 16384,
    "P100": 16384,
    "P40": 24576,
}


def scenario_for_container(namespace: str, container: str) -> str:
    """Deterministically assign a CPU/memory scenario based on namespace/container hash."""
    h = hashlib.md5(f"{namespace}/{container}".encode()).hexdigest()
    v = int(h[:8], 16) % 100
    if v < 40:
        return "over_provisioned"
    elif v < 70:
        return "under_provisioned"
    elif v < 90:
        return "well_sized"
    else:
        return "memory_pressure"


# Explicit scenario overrides for known test pods from the example YAML.
# This guarantees every classification path is covered in E2E tests.
_GPU_SCENARIO_OVERRIDES = {
    ("ml-training", "llm-finetune"): "underutilized",
    ("ml-training", "abandoned-notebook"): "idle",
    ("ml-training", "data-preprocessor"): "underutilized",
    ("ml-inference", "embedding-server"): "underutilized",
    # legacy-vision-model / recommendation-model: V100 Tier 2 → no_profiling automatically.
    # gpu-worker-1 (A100): 2 underutilized + 1 idle → 2/2 eligible = 100% candidates → time-slicing fires.
    # gpu-worker-2 (A10G): 1 underutilized / 1 eligible = 100% → time-slicing fires.
}


def gpu_scenario_for_container(namespace: str, container: str, model: str) -> str:
    """Deterministically assign a GPU scenario.

    Checks explicit overrides first, then falls back to hash-based
    assignment.  Tier 2 GPUs always get 'no_profiling'.
    """
    if model not in TIER1_GPU_MODELS:
        return "no_profiling"
    override = _GPU_SCENARIO_OVERRIDES.get((namespace, container))
    if override:
        return override
    h = hashlib.md5(f"gpu:{namespace}/{container}".encode()).hexdigest()
    v = int(h[:8], 16) % 100
    if v < 15:
        return "idle"
    elif v < 40:
        return "underutilized"
    elif v < 50:
        return "memory_bound"
    else:
        return "well_utilized"


def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _scenario_usage(scenario, cpu_req, cpu_lim, mem_req, mem_lim):
    """Return (cpu_use_avg, cpu_use_max, mem_use_avg, mem_use_max, oom) for a scenario."""
    if scenario == "over_provisioned":
        cpu_avg = cpu_req * random.uniform(0.25, 0.50)
        cpu_max = cpu_avg * random.uniform(1.1, 1.4)
        mem_avg = mem_req * random.uniform(0.25, 0.50)
        mem_max = mem_avg * random.uniform(1.05, 1.3)
        return cpu_avg, cpu_max, mem_avg, mem_max, 0
    if scenario == "under_provisioned":
        cpu_avg = cpu_req * random.uniform(1.2, 2.0)
        cpu_max = min(cpu_avg * random.uniform(1.1, 1.5), cpu_lim * 0.95)
        mem_avg = mem_req * random.uniform(1.2, 1.8)
        mem_max = min(mem_avg * random.uniform(1.1, 1.3), mem_lim * 0.95)
        return cpu_avg, cpu_max, mem_avg, mem_max, 0
    if scenario == "well_sized":
        cpu_avg = cpu_req * random.uniform(0.65, 0.90)
        cpu_max = cpu_avg * random.uniform(1.05, 1.2)
        mem_avg = mem_req * random.uniform(0.65, 0.90)
        mem_max = mem_avg * random.uniform(1.05, 1.15)
        return cpu_avg, cpu_max, mem_avg, mem_max, 0
    # memory_pressure
    cpu_avg = cpu_req * random.uniform(0.5, 0.8)
    cpu_max = cpu_avg * random.uniform(1.1, 1.3)
    mem_avg = mem_lim * random.uniform(0.85, 0.98)
    mem_max = mem_lim * random.uniform(1.0, 1.1)
    return cpu_avg, cpu_max, mem_avg, mem_max, random.randint(1, 5)


def _normalize_resources(cpu_req, cpu_lim, mem_req, mem_lim):
    """Clamp raw nise values to realistic Kubernetes resource ranges."""
    cpu_req = max(cpu_req, 0.5) if cpu_req > 0 else 0.5
    cpu_lim = max(cpu_lim, cpu_req * 2) if cpu_lim > 0 else cpu_req * 2
    mem_req = max(mem_req, 512 * MIB) if mem_req > 0 else 512 * MIB
    mem_lim = max(mem_lim, mem_req * 2) if mem_lim > 0 else mem_req * 2

    cpu_req = clamp(cpu_req * 0.15, 0.05, 4.0)
    cpu_lim = clamp(cpu_req * random.uniform(1.5, 2.5), cpu_req, 8.0)
    mem_req_gib = clamp(mem_req / GIB * 0.3, 0.064, 8.0)
    mem_req = mem_req_gib * GIB
    mem_lim = mem_req * random.uniform(1.5, 2.5)
    return cpu_req, cpu_lim, mem_req, mem_lim


def process_row(row: dict, scenario: str) -> dict:
    cpu_req, cpu_lim, mem_req, mem_lim = _normalize_resources(
        float(row["cpu_request_container_avg"]),
        float(row["cpu_limit_container_avg"]),
        float(row["memory_request_container_avg"]),
        float(row["memory_limit_container_avg"]),
    )
    cpu_use_avg, cpu_use_max, mem_use_avg, mem_use_max, oom = _scenario_usage(
        scenario, cpu_req, cpu_lim, mem_req, mem_lim
    )

    cpu_use_min = cpu_use_avg * random.uniform(0.5, 0.8)
    mem_use_min = int(mem_use_avg * random.uniform(0.5, 0.8))

    cpu_throttle_avg = 0.0
    cpu_throttle_max = 0.0
    if scenario == "under_provisioned":
        cpu_throttle_avg = cpu_req * random.uniform(0.05, 0.15)
        cpu_throttle_max = cpu_throttle_avg * random.uniform(1.5, 3.0)

    mem_rss_avg = int(mem_use_avg * random.uniform(0.85, 0.95))
    mem_rss_min = int(mem_rss_avg * random.uniform(0.7, 0.9))
    mem_rss_max = int(mem_rss_avg * random.uniform(1.05, 1.15))

    def f(v):
        return f"{v:.5f}"

    def i(v):
        return str(int(v))

    row["cpu_request_container_avg"] = f(cpu_req)
    row["cpu_request_container_sum"] = f(cpu_req)
    row["cpu_limit_container_avg"] = f(cpu_lim)
    row["cpu_limit_container_sum"] = f(cpu_lim)
    row["cpu_usage_container_avg"] = f(cpu_use_avg)
    row["cpu_usage_container_min"] = f(cpu_use_min)
    row["cpu_usage_container_max"] = f(cpu_use_max)
    row["cpu_usage_container_sum"] = f(cpu_use_avg)
    row["cpu_throttle_container_avg"] = f(cpu_throttle_avg)
    row["cpu_throttle_container_max"] = f(cpu_throttle_max)
    row["cpu_throttle_container_sum"] = f(cpu_throttle_avg)
    row["memory_request_container_avg"] = i(mem_req)
    row["memory_request_container_sum"] = i(mem_req)
    row["memory_limit_container_avg"] = i(mem_lim)
    row["memory_limit_container_sum"] = i(mem_lim)
    row["memory_usage_container_avg"] = i(mem_use_avg)
    row["memory_usage_container_min"] = i(mem_use_min)
    row["memory_usage_container_max"] = i(mem_use_max)
    row["memory_usage_container_sum"] = i(mem_use_avg)
    row["memory_rss_usage_container_avg"] = i(mem_rss_avg)
    row["memory_rss_usage_container_min"] = i(mem_rss_min)
    row["memory_rss_usage_container_max"] = i(mem_rss_max)
    row["memory_rss_usage_container_sum"] = i(mem_rss_avg)
    row["oom_count"] = str(oom)
    return row


def _gpu_scenario_metrics(scenario, model, fb_capacity):
    """Return GPU metric values for a given scenario.

    Returns a dict with all 12 GPU metric columns (min/max/avg for
    tensor, dram, sm, and frame-buffer).  For 'no_profiling', the
    profiling columns are empty strings (Tier 2 GPU).
    """

    def _spread(avg, lo_frac=0.3, hi_frac=1.5, cap=1.0):
        mn = max(0.0, avg * random.uniform(lo_frac, 0.9))
        mx = min(cap, avg * random.uniform(1.1, hi_frac))
        return mn, mx

    fb_avg = fb_capacity * random.uniform(0.1, 0.9)
    fb_min = max(0.0, fb_avg * random.uniform(0.5, 0.95))
    fb_max = min(fb_capacity, fb_avg * random.uniform(1.05, 1.5))

    if scenario == "no_profiling":
        return {
            "accelerator_frame_buffer_usage_avg": f"{fb_avg:.1f}",
            "accelerator_frame_buffer_usage_min": f"{fb_min:.1f}",
            "accelerator_frame_buffer_usage_max": f"{fb_max:.1f}",
            "tensor_pipe_active_avg": "",
            "tensor_pipe_active_min": "",
            "tensor_pipe_active_max": "",
            "dram_active_avg": "",
            "dram_active_min": "",
            "dram_active_max": "",
            "sm_active_avg": "",
            "sm_active_min": "",
            "sm_active_max": "",
        }

    if scenario == "idle":
        sm = random.uniform(0.001, 0.015)
        tensor = random.uniform(0.0, 0.005)
        dram = random.uniform(0.005, 0.02)
        fb_avg = fb_capacity * random.uniform(0.001, 0.01)
    elif scenario == "underutilized":
        sm = random.uniform(0.05, 0.20)
        tensor = random.uniform(0.01, 0.12)
        dram = random.uniform(0.05, 0.25)
        fb_avg = fb_capacity * random.uniform(0.03, 0.15)
    elif scenario == "memory_bound":
        sm = random.uniform(0.15, 0.40)
        tensor = random.uniform(0.02, 0.12)
        dram = random.uniform(0.65, 0.90)
        fb_avg = fb_capacity * random.uniform(0.60, 0.90)
    else:  # well_utilized
        sm = random.uniform(0.40, 0.85)
        tensor = random.uniform(0.25, 0.75)
        dram = random.uniform(0.30, 0.70)
        fb_avg = fb_capacity * random.uniform(0.40, 0.80)

    sm_min, sm_max = _spread(sm)
    tensor_min, tensor_max = _spread(tensor)
    dram_min, dram_max = _spread(dram)
    fb_min = max(0.0, fb_avg * random.uniform(0.5, 0.95))
    fb_max = min(fb_capacity, fb_avg * random.uniform(1.05, 1.5))

    return {
        "accelerator_frame_buffer_usage_avg": f"{fb_avg:.1f}",
        "accelerator_frame_buffer_usage_min": f"{fb_min:.1f}",
        "accelerator_frame_buffer_usage_max": f"{fb_max:.1f}",
        "tensor_pipe_active_avg": f"{tensor:.4f}",
        "tensor_pipe_active_min": f"{tensor_min:.4f}",
        "tensor_pipe_active_max": f"{tensor_max:.4f}",
        "dram_active_avg": f"{dram:.4f}",
        "dram_active_min": f"{dram_min:.4f}",
        "dram_active_max": f"{dram_max:.4f}",
        "sm_active_avg": f"{sm:.4f}",
        "sm_active_min": f"{sm_min:.4f}",
        "sm_active_max": f"{sm_max:.4f}",
    }


def apply_gpu_scenario(row: dict) -> tuple[dict, str]:
    """Apply a GPU scenario to a row if it has a GPU.

    Returns (modified_row, scenario_name).  If no GPU is present,
    returns (row, "no_gpu").
    """
    model = row.get("accelerator_model_name", "").strip()
    if not model:
        return row, "no_gpu"

    ns = row.get("namespace", "")
    container = row.get("container_name", "")
    scenario = gpu_scenario_for_container(ns, container, model)
    fb_capacity = GPU_FB_CAPACITY.get(model, 15360)

    gpu_metrics = _gpu_scenario_metrics(scenario, model, fb_capacity)
    row.update(gpu_metrics)
    return row, scenario


def _find_ros_container_files(input_dir):
    """Locate ROS container-level CSV files.

    Tries the manifest first (``resource_optimization_files``), then falls
    back to glob patterns.  Only container-level files are returned —
    namespace-level files (``ros-openshift-namespace-*``) are excluded.
    """
    manifest_path = os.path.join(input_dir, "manifest.json")
    if os.path.exists(manifest_path):
        import json

        with open(manifest_path) as f:
            manifest = json.load(f)
        ros_files = manifest.get("resource_optimization_files", [])
        container_files = [
            os.path.join(input_dir, fn)
            for fn in ros_files
            if "namespace" not in fn and os.path.exists(os.path.join(input_dir, fn))
        ]
        if container_files:
            return sorted(container_files)

    for pattern in ("*ocp_ros_usage*.csv", "*-ocp_ros_usage-*.csv", "*_openshift_report.*.csv"):
        hits = sorted(glob.glob(os.path.join(input_dir, pattern)))
        container_hits = [h for h in hits if "namespace" not in os.path.basename(h)]
        if container_hits:
            return container_hits
    return []


def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} INPUT_DIR OUTPUT_DIR CLUSTER_UUID", file=sys.stderr)
        sys.exit(1)

    input_dir, output_dir, _cluster_uuid = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(output_dir, exist_ok=True)
    random.seed(42)

    input_files = _find_ros_container_files(input_dir)
    if not input_files:
        print(f"No ROS container CSV files found in {input_dir}", file=sys.stderr)
        sys.exit(1)

    cpu_counts, gpu_counts, total_rows = _process_ros_files(input_files, output_dir)
    _print_summary(cpu_counts, gpu_counts, total_rows, len(input_files), output_dir)
    _copy_remaining_files(input_dir, input_files, output_dir)


def _process_ros_files(input_files, output_dir):
    """Process each ROS container CSV and return scenario counters."""
    cpu_counts = {"over_provisioned": 0, "under_provisioned": 0, "well_sized": 0, "memory_pressure": 0}
    gpu_counts = {
        "idle": 0,
        "underutilized": 0,
        "memory_bound": 0,
        "well_utilized": 0,
        "no_profiling": 0,
        "no_gpu": 0,
    }
    total_rows = 0
    for fpath in input_files:
        fname = os.path.basename(fpath)
        outpath = os.path.join(output_dir, fname)
        with open(fpath, newline="") as fin, open(outpath, "w", newline="") as fout:
            reader = csv.DictReader(fin)
            writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
            writer.writeheader()
            for row in reader:
                scenario = scenario_for_container(row["namespace"], row["container_name"])
                row = process_row(row, scenario)
                row, gpu_scenario = apply_gpu_scenario(row)
                writer.writerow(row)
                cpu_counts[scenario] += 1
                gpu_counts[gpu_scenario] += 1
                total_rows += 1
    return cpu_counts, gpu_counts, total_rows


def _print_summary(cpu_counts, gpu_counts, total_rows, num_files, output_dir):
    """Print scenario distribution summary."""
    print(f"Processed {total_rows} rows across {num_files} ROS files → {output_dir}")
    print("\n  CPU/Memory scenarios:")
    for s, c in sorted(cpu_counts.items()):
        pct = c / total_rows * 100
        print(f"    {s}: {c} rows ({pct:.1f}%)")
    gpu_total = sum(v for k, v in gpu_counts.items() if k != "no_gpu")
    if gpu_total > 0:
        print(f"\n  GPU scenarios ({gpu_total} GPU rows):")
        for s, c in sorted(gpu_counts.items()):
            if s == "no_gpu":
                continue
            pct = c / gpu_total * 100
            print(f"    {s}: {c} rows ({pct:.1f}%)")


def _copy_remaining_files(input_dir, input_files, output_dir):
    """Copy all non-processed files (manifest, namespace ROS, etc.)."""
    processed_basenames = {os.path.basename(f) for f in input_files}
    all_files = glob.glob(os.path.join(input_dir, "*"))
    copied = 0
    for fpath in all_files:
        fname = os.path.basename(fpath)
        if fname in processed_basenames:
            continue
        outpath = os.path.join(output_dir, fname)
        if not os.path.exists(outpath):
            shutil.copy2(fpath, outpath)
            copied += 1
    print(f"Copied {copied} other files to {output_dir}")


if __name__ == "__main__":
    main()
