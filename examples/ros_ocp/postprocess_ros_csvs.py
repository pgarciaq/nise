#!/usr/bin/env python3
"""Post-process nise-generated ROS CSVs to produce realistic usage patterns.

Nise generates random container names with usage drawn from a wide uniform
distribution that often far exceeds requests, making every recommendation
say "increase dramatically."  This script replaces the usage columns with
values that create a realistic mix of recommendation scenarios:

  - Over-provisioned  (40%): usage ~30-50% of request  → "decrease request"
  - Under-provisioned (30%): usage ~120-200% of request → "increase request"
  - Well-sized        (20%): usage ~70-95% of request   → minor / no change
  - Memory-pressure   (10%): normal CPU, memory near limit, OOM events

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


def scenario_for_container(namespace: str, container: str) -> str:
    """Deterministically assign a scenario based on namespace/container hash."""
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


def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} INPUT_DIR OUTPUT_DIR CLUSTER_UUID", file=sys.stderr)
        sys.exit(1)

    input_dir, output_dir, cluster_uuid = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(output_dir, exist_ok=True)
    random.seed(42)

    ros_pattern = os.path.join(input_dir, f"*{cluster_uuid}*-ocp_ros_usage-*.csv")
    input_files = sorted(glob.glob(ros_pattern))
    if not input_files:
        print(f"No ROS files matching *{cluster_uuid}*-ocp_ros_usage-*.csv in {input_dir}", file=sys.stderr)
        sys.exit(1)

    scenarios_count = {"over_provisioned": 0, "under_provisioned": 0, "well_sized": 0, "memory_pressure": 0}
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
                writer.writerow(row)
                scenarios_count[scenario] += 1
                total_rows += 1

    print(f"Processed {total_rows} rows across {len(input_files)} ROS files → {output_dir}")
    for s, c in sorted(scenarios_count.items()):
        pct = c / total_rows * 100
        print(f"  {s}: {c} rows ({pct:.1f}%)")

    # Copy non-ROS CSVs (pod_usage, storage, node_label, etc.)
    all_csvs = glob.glob(os.path.join(input_dir, f"*{cluster_uuid}*.csv"))
    copied = 0
    for fpath in all_csvs:
        fname = os.path.basename(fpath)
        if "ocp_ros_usage-" in fname:
            continue
        outpath = os.path.join(output_dir, fname)
        if not os.path.exists(outpath):
            shutil.copy2(fpath, outpath)
            copied += 1
    print(f"Copied {copied} non-ROS CSV files to {output_dir}")


if __name__ == "__main__":
    main()
