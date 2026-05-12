#!/bin/bash
# Generate realistic OCP + ROS test data for ros-ocp-backend.
#
# Produces a tarball ready to upload via the cost-onprem ingress endpoint
# or the Koku ingest_ocp_payload masu API.
#
# Usage:
#   ./generate_ros_data.sh [CLUSTER_UUID]
#
# Requirements:
#   - nise installed (pip install koku-nise, or run from the nise repo venv)
#   - python3 with stdlib only (no extra dependencies)
#
# Output:
#   /tmp/ros_test_data/upload.tar.gz   — tarball with manifest + all CSVs
#   /tmp/ros_test_data/output/         — individual post-processed CSV files

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_UUID="${1:-a1b2c3d4-e5f6-7890-abcd-111111111111}"
WORK_DIR="/tmp/ros_test_data"
NISE_OUTPUT="${WORK_DIR}/nise_raw"
PROCESSED="${WORK_DIR}/output"

echo "=== Generating ROS test data ==="
echo "Cluster UUID: ${CLUSTER_UUID}"
echo "Output:       ${WORK_DIR}/upload.tar.gz"
echo ""

rm -rf "${WORK_DIR}"
mkdir -p "${NISE_OUTPUT}" "${PROCESSED}"

# Step 1: Generate raw data with nise.
# Run nise from within NISE_OUTPUT since -w writes to CWD.
echo "[1/4] Running nise to generate OCP + ROS data..."
(
    cd "${NISE_OUTPUT}"
    nise report ocp \
        --static-report-file "${SCRIPT_DIR}/ocp_static_data.yml" \
        --ocp-cluster-id "${CLUSTER_UUID}" \
        -w --ros-ocp-info
)
echo "       Generated $(find "${NISE_OUTPUT}" -name '*.csv' | wc -l) CSV files"

# Step 2: Post-process ROS CSVs for realistic usage patterns.
# The postprocess script also copies all non-ROS files to PROCESSED.
echo "[2/4] Post-processing ROS CSVs..."
python3 "${SCRIPT_DIR}/postprocess_ros_csvs.py" \
    "${NISE_OUTPUT}" "${PROCESSED}" "${CLUSTER_UUID}"

# Step 3: Build manifest.json
echo "[3/4] Creating manifest.json..."

# Collect OCP cost/usage files (for Koku listener processing)
OCP_FILES=$(cd "${PROCESSED}" && ls \
    *ocp_pod_usage*.csv \
    *ocp_storage_usage*.csv \
    *ocp_node_label*.csv \
    *ocp_namespace_label*.csv \
    *ocp_vm_usage*.csv \
    *ocp_gpu_usage*.csv \
    2>/dev/null | sort || true)

# Collect ROS files (for ros-ocp-backend processor).
# Includes: container ROS, namespace ROS, storage (PVC), and snapshot inventory.
ROS_FILES=$(cd "${PROCESSED}" && ls \
    *ocp_ros_usage*.csv \
    *ocp_ros_namespace_usage*.csv \
    *ocp_storage_usage*.csv \
    *ocp_snapshot_inventory*.csv \
    2>/dev/null | sort | uniq || true)

TODAY=$(date +%Y-%m-%d)
START_DATE=$(grep 'start_date:' "${SCRIPT_DIR}/ocp_static_data.yml" | head -1 | awk '{print $2}')
END_DATE=$(grep 'end_date:' "${SCRIPT_DIR}/ocp_static_data.yml" | head -1 | awk '{print $2}')

python3 -c "
import json, uuid
ocp = [f.strip() for f in '''${OCP_FILES}'''.strip().split('\n') if f.strip()]
ros = [f.strip() for f in '''${ROS_FILES}'''.strip().split('\n') if f.strip()]
manifest = {
    'uuid': str(uuid.uuid4()),
    'cluster_id': '${CLUSTER_UUID}',
    'version': '${TODAY}',
    'date': '${TODAY}',
    'start': '${START_DATE}',
    'end': '${END_DATE}',
    'files': ocp,
    'resource_optimization_files': ros,
}
with open('${PROCESSED}/manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)
print(f'       {len(ocp)} OCP files, {len(ros)} ROS files')
"

# Step 4: Create tarball (no ./ prefix — filenames must match manifest exactly)
echo "[4/4] Creating tarball..."
(cd "${PROCESSED}" && tar czf "${WORK_DIR}/upload.tar.gz" *)

SIZE=$(du -h "${WORK_DIR}/upload.tar.gz" | cut -f1)
echo ""
echo "=== Done ==="
echo "Tarball: ${WORK_DIR}/upload.tar.gz (${SIZE})"
echo ""
echo "To upload to a cost-onprem deployment:"
echo "  curl -X POST -H 'Authorization: Bearer \$TOKEN' \\"
echo "    -F 'file=@${WORK_DIR}/upload.tar.gz;type=application/vnd.redhat.hccm.tar+tgz' \\"
echo "    https://GATEWAY_HOST/api/ingress/v1/upload"
