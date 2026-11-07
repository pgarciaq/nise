"""#772 (V15-22) regression suite: packaging must preserve ROS/HCP family names.

The packaging loop special-cased only 4 of the 11 ROS-family members with
recognized upload names; the else fallback renamed the remaining SEVEN to
{uuid}_openshift_report.N.csv — OCP_ROS_USAGE (the ROS container file),
OCP_ROS_VM_GPU_DEVICE and OCP_ROS_VM_PVC (the companions), and the HCP
quartet (capacity/nodepool/SLO/api-tax). ROS's DetermineCSVType recognizes
neither the generic name nor a compensating header, so the server dispatch
marked them done without ingestion ("no capacity snapshot in this payload").

The fix preserves each fall-through family's original basename — every one
already carries a recognized token in its monthly name.

The family tokens below mirror ros-ocp-backend's DetermineCSVType rules
(internal/utils/utils.go) — the contract this test pins. The end-to-end
consumer validation (a freshly built robne CLI over raw vs packaged
fixtures) is the acceptance layer, recorded in the plan.
"""

import datetime
import json
import unittest
import os
import re
import tempfile
from unittest.mock import patch

from nise.report import ocp_create_report


# The ROS DetermineCSVType contract (both phases), mirrored: every packaged
# ROS-family filename must carry at least one of these tokens.
ROS_FAMILY_TOKENS = (
    "ros-openshift-container-",
    "ocp_ros_usage",
    "ros-openshift-namespace-",
    "ocp_ros_namespace",
    "ros-openshift-cluster-quota-",
    "ocp_ros_cluster_quota",
    "ros-openshift-vm-usage-",
    "ocp_ros_vm_usage",
    "ros-openshift-vm-gpu-device-",
    "ocp_ros_vm_gpu_device",
    "ros-openshift-vm-pvc-",
    "ocp_ros_vm_pvc",
    "ros-openshift-snapshot-",
    "ocp_snapshot_inventory",
    "cm-openshift-snapshot-inventory",
    "ros-openshift-hcp-capacity-",
    "ros-openshift-nodepool-",
    "ros-openshift-slo-",
    "ros-openshift-apitax-",
)

# The generic erasure pattern: {uuid}_openshift_report.N.csv.
GENERIC_NAME_RE = re.compile(r"^[0-9a-f-]{36}_openshift_report\.\d+\.csv$")

# Per-family expectations for the driven static report: the HCP quartet's
# KMO-contract tokens, the companions' and the container's nise-style tokens.
EXPECTED_FAMILY_TOKENS = {
    "ros-openshift-hcp-capacity-": "HCP capacity",
    "ros-openshift-nodepool-": "NodePool",
    "ros-openshift-slo-": "SLO",
    "ros-openshift-apitax-": "API-tax",
    "ocp_ros_vm_gpu_device": "VM GPU-device companion",
    "ocp_ros_vm_pvc": "VM PVC companion",
    "ocp_ros_usage": "ROS container",
}


class PackagingFamilyPreservationTest(unittest.TestCase):
    """The packaging path must not erase family identity (#772)."""

    def _generate_payload(self, row_limit=None):
        """Drive ocp_create_report through the packaging path; return the
        payload dir's manifest.json contents (the test_manifest_override
        pattern)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_dir = os.path.join(tmpdir, "payload")
            os.mkdir(payload_dir)
            # create_temporary_copy targets gettempdir()/payload — isolate it
            # so repeated runs neither accumulate nor scan stale copies.
            # tempfile.tempdir takes precedence over the environment (and
            # gettempdir() may already be cached).
            prev_tmpdir = tempfile.tempdir
            tempfile.tempdir = tmpdir
            prev_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                attributes = {
                    "start_date": "2026-10-25",
                    "end_date": "2026-10-26",
                    # The attribute-gated KMO-contract report types (#728's pattern).
                    "hcp_capacity": {},
                    "nodepool": {},
                    "slo": {},
                    "apitax": {},
                }
                options = {
                    "start_date": datetime.datetime(2026, 10, 25),
                    "end_date": datetime.datetime(2026, 10, 26),
                    "ocp_cluster_id": "test-cluster-772",
                    "static_report_data": {"generators": [{"OCPGenerator": attributes}]},
                    "ros_ocp_info": True,  # registers the gated reports + the VM generator
                    "ros_only": True,  # the ROS container file
                    "insights_upload": payload_dir,  # the packaging path
                    "row_limit": row_limit or 100000,
                    "write_monthly": True,
                }
                with patch("nise.report.post_payload_to_ingest_service", return_value=None):
                    ocp_create_report(options)
            finally:
                os.chdir(prev_cwd)
                tempfile.tempdir = prev_tmpdir
            manifests = []
            for root, _dirs, files in os.walk(payload_dir):
                manifests.extend(os.path.join(root, f) for f in files if f == "manifest.json")
            self.assertTrue(manifests, "payload extraction must produce manifest.json")
            with open(manifests[0]) as handle:
                manifest = json.load(handle)
            ros_names = manifest.get("resource_optimization_files") or []
            return manifest, ros_names

    def test_packaged_ros_files_carry_family_identity(self):
        """RED on baseline: every packaged ROS-family filename must carry a
        recognized family token — the generic rename erases seven families'
        identity and the server marks them done without ingestion (#772)."""
        _manifest, entries = self._generate_payload()
        self.assertTrue(entries, "the driven static report must produce ROS files")

        generic = [e for e in entries if GENERIC_NAME_RE.match(os.path.basename(e))]
        self.assertEqual(
            [],
            generic,
            f"packaging renamed {len(generic)} ROS files to the generic "
            f"openshift_report.N form — ROS cannot dispatch them and marks them "
            f"done without ingesting (#772): {generic}",
        )
        for entry in entries:
            self.assertTrue(
                any(token in entry for token in ROS_FAMILY_TOKENS),
                f"packaged file {entry} carries no recognized family token (#772)",
            )
        # The seven fall-through families carry the assembly-id prefix: koku's
        # ROS S3 key is source/date/filename without the manifest id, so bare
        # monthly names would let a same-day re-upload overwrite the earlier
        # object, and the shared packaging temp dir would collide across
        # concurrent runs (#772 review findings).
        for token in EXPECTED_FAMILY_TOKENS:
            matching = [e for e in entries if token in e]
            for e in matching:
                self.assertRegex(
                    e,
                    r"^[0-9a-f-]{36}-",
                    f"the preserved family name must carry the assembly-id prefix for "
                    f"upload uniqueness: {e} (#772 review finding)",
                )

    def test_each_expected_family_survives_packaging(self):
        """The seven fall-through families specifically: HCP capacity,
        NodePool, SLO, API-tax, the VM companions, and the ROS container
        file must each be recognizable in the packaged manifest."""
        _manifest, entries = self._generate_payload()
        joined = "\n".join(entries)
        for token, label in EXPECTED_FAMILY_TOKENS.items():
            self.assertIn(
                token,
                joined,
                f"the {label} family's identity did not survive packaging (no '{token}' in the packaged names) (#772)",
            )

    def test_split_files_preserve_family_identity(self):
        """Row-limit split parts (where legal) keep their family token —
        the split number is inherent in the preserved basename. The HCP
        kinds are one-file-per-month by contract (write_ocp_file raises on
        split) so this drives the SPLITTABLE families only."""
        start = datetime.datetime(2026, 10, 25)
        end = datetime.datetime(2026, 10, 26)
        with tempfile.TemporaryDirectory() as tmpdir:
            payload_dir = os.path.join(tmpdir, "payload")
            os.mkdir(payload_dir)
            prev_tmpdir = tempfile.tempdir
            tempfile.tempdir = tmpdir
            prev_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                options = {
                    "start_date": start,
                    "end_date": end,
                    "ocp_cluster_id": "test-cluster-772",
                    # No HCP-gated blocks: those are one-file-per-month by
                    # contract (write_ocp_file raises on split); this drives
                    # the SPLITTABLE families (container + companions).
                    "static_report_data": {
                        "generators": [{"OCPGenerator": {"start_date": "2026-10-25", "end_date": "2026-10-26"}}]
                    },
                    "ros_ocp_info": True,  # the VM generator (companions split)
                    "ros_only": True,  # the container file (splits)
                    "insights_upload": payload_dir,
                    "row_limit": 500,  # splits the hourly reports into a handful of parts
                    "write_monthly": True,
                }
                with patch("nise.report.post_payload_to_ingest_service", return_value=None):
                    ocp_create_report(options)
            finally:
                os.chdir(prev_cwd)
                tempfile.tempdir = prev_tmpdir
            manifests = []
            for root, _dirs, files in os.walk(payload_dir):
                manifests.extend(os.path.join(root, f) for f in files if f == "manifest.json")
            self.assertTrue(manifests)
            with open(manifests[0]) as handle:
                manifest = json.load(handle)
            entries = manifest.get("resource_optimization_files") or []
        self.assertTrue(entries, "the split report must produce ROS files")
        split_parts = [e for e in entries if re.search(r"[-.](\d+)\.csv$", e)]
        self.assertTrue(split_parts, "the row limit must actually split something")
        for entry in entries:
            basename = os.path.basename(entry)
            self.assertFalse(
                GENERIC_NAME_RE.match(basename),
                f"split part {basename} was renamed to the generic form (#772)",
            )
            self.assertTrue(
                any(token in entry for token in ROS_FAMILY_TOKENS),
                f"split part {entry} carries no recognized family token (#772)",
            )
