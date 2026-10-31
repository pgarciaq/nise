"""Tests for the manifest cr_status template override (#726).

The override lets a static-report template carry cr_status content that
deep-merges over nise's hardcoded defaults — the W8/advisory parity
fixtures need manifest.json files with cr_status.topology (hcpSnapshot
entries carrying hostedClusterID, complete, observedAt, hcTier).

Relative markers: string values shaped `now` / `now-<n><m|h|d>` resolve
against the generation clock, so fixtures stay regenerable (generate
today, consume today). Everything else passes through verbatim.
"""

import unittest
from datetime import datetime, timedelta, UTC

from nise.manifest import apply_manifest_cr_status_override
from nise.manifest import resolve_relative_markers

from unittest import TestCase

# The hardcoded base (the shape report.py builds today). One key per
# nesting level so a mis-merge cannot pass by coincidence.
BASE_CR_STATUS = {
    "clusterID": "4e009161-4f40-42c8-877c-3e59f6baea3d",
    "clusterVersion": "stable-4.6",
    "api_url": "https://console.redhat.com",
    "authentication": {"type": "token"},
    "upload": {"ingress_path": "/api/ingress/v1/upload", "upload_cycle": 360},
}

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)


class DeepMergeTest(unittest.TestCase):
    """Merge semantics: recursive on dicts, replacement on lists/scalars."""

    def test_no_override_returns_base_unchanged(self):
        """No manifest key in the template means today's manifest, byte-identical."""
        self.assertIs(apply_manifest_cr_status_override(BASE_CR_STATUS, None, NOW), BASE_CR_STATUS)
        self.assertEqual(apply_manifest_cr_status_override(BASE_CR_STATUS, {}, NOW), BASE_CR_STATUS)

    def test_no_static_data_returns_base_unchanged(self):
        """A template without a manifest block (the common case) is a no-op."""
        self.assertIs(apply_manifest_cr_status_override(BASE_CR_STATUS, None, NOW), BASE_CR_STATUS)

    def test_partial_override_keeps_siblings(self):
        """Adding topology must not disturb the hardcoded keys."""
        override = {"topology": {"hostedControlPlaneNamespaces": ["clusters-hc9"]}}
        merged = apply_manifest_cr_status_override(BASE_CR_STATUS, override, NOW)
        self.assertEqual(merged["clusterID"], BASE_CR_STATUS["clusterID"])
        self.assertEqual(merged["authentication"], {"type": "token"})
        self.assertEqual(merged["topology"]["hostedControlPlaneNamespaces"], ["clusters-hc9"])

    def test_nested_dict_merges_recursively(self):
        """A nested override merges into the nested dict, not replaces it."""
        override = {"upload": {"upload_cycle": 720}}
        merged = apply_manifest_cr_status_override(BASE_CR_STATUS, override, NOW)
        self.assertEqual(merged["upload"]["upload_cycle"], 720)
        self.assertEqual(merged["upload"]["ingress_path"], "/api/ingress/v1/upload")

    def test_override_wins_on_scalars(self):
        override = {"clusterVersion": "stable-4.16"}
        merged = apply_manifest_cr_status_override(BASE_CR_STATUS, override, NOW)
        self.assertEqual(merged["clusterVersion"], "stable-4.16")
        self.assertEqual(merged["clusterID"], BASE_CR_STATUS["clusterID"])

    def test_lists_replaced_wholesale(self):
        """hcpSnapshot entries are replacements, never element-merged."""
        override = {
            "topology": {
                "hcpSnapshot": [
                    {"hcpNamespace": "clusters-hc9", "hostedClusterID": "hc-1", "complete": True},
                ]
            }
        }
        merged = apply_manifest_cr_status_override(BASE_CR_STATUS, override, NOW)
        self.assertEqual(len(merged["topology"]["hcpSnapshot"]), 1)
        self.assertEqual(merged["topology"]["hcpSnapshot"][0]["hostedClusterID"], "hc-1")


class RelativeMarkerTest(unittest.TestCase):
    """The now / now-<n><m|h|d> grammar, resolved against the clock."""

    def test_now_resolves_to_clock(self):
        self.assertEqual(resolve_relative_markers("now", NOW), "2026-10-31T12:00:00Z")

    def test_offsets_resolve(self):
        self.assertEqual(resolve_relative_markers("now-1h", NOW), "2026-10-31T11:00:00Z")
        self.assertEqual(resolve_relative_markers("now-90m", NOW), "2026-10-31T10:30:00Z")
        self.assertEqual(resolve_relative_markers("now-2d", NOW), "2026-10-29T12:00:00Z")
        self.assertEqual(resolve_relative_markers("now-45s", NOW), "2026-10-31T11:59:15Z")

    def test_non_markers_pass_through(self):
        """Version strings, URLs, label values: untouched."""
        for literal in ("stable-4.6", "non-prod", "nowhere", "known-1h-later", "", "NOW"):
            self.assertEqual(resolve_relative_markers(literal, NOW), literal)

    def test_recurses_dicts_and_lists(self):
        value = {
            "topology": {
                "hcpSnapshot": [
                    {"observedAt": "now-30m", "hcTier": "non-prod", "hcUID": "uid-1"},
                    {"observedAt": "now-2h", "complete": True},
                ],
                "hostedControlPlaneNamespaces": ["clusters-hc9"],
            }
        }
        resolved = resolve_relative_markers(value, NOW)
        entries = resolved["topology"]["hcpSnapshot"]
        self.assertEqual(entries[0]["observedAt"], "2026-10-31T11:30:00Z")
        self.assertEqual(entries[0]["hcTier"], "non-prod")
        self.assertEqual(entries[0]["hcUID"], "uid-1")
        self.assertEqual(entries[1]["observedAt"], "2026-10-31T10:00:00Z")
        self.assertIs(entries[1]["complete"], True)
        self.assertEqual(resolved["topology"]["hostedControlPlaneNamespaces"], ["clusters-hc9"])

    def test_non_string_scalars_untouched(self):
        self.assertEqual(resolve_relative_markers(42, NOW), 42)
        self.assertIs(resolve_relative_markers(True, NOW), True)
        self.assertIsNone(resolve_relative_markers(None, NOW))

    def test_offsets_do_not_mutate_the_clock(self):
        """Repeated resolution is stable (no shared-state drift)."""
        self.assertEqual(resolve_relative_markers("now-1h", NOW), resolve_relative_markers("now-1h", NOW))

    def test_negative_offsets_only(self):
        """Future offsets are not part of the grammar (fixtures look back)."""
        for bad in ("now+1h", "now-1w", "now--1h", "now-1", "now-h"):
            self.assertEqual(resolve_relative_markers(bad, NOW), bad, f"{bad} must pass through unchanged")


class OverrideWithMarkersTest(unittest.TestCase):
    """The composed path report.py calls: merge + resolve in one step."""

    def test_topology_with_markers(self):
        override = {
            "topology": {
                "hostedControlPlaneNamespaces": ["clusters-hc9"],
                "hcpSnapshot": [
                    {
                        "hcpNamespace": "clusters-hc9",
                        "hostedClusterID": "bbbbbbbb-1111-1111-1111-111111111111",
                        "hcUID": "uid-hc-1",
                        "observedAt": "now-30m",
                        "complete": True,
                        "hcTier": "non-prod",
                    }
                ],
            }
        }
        merged = apply_manifest_cr_status_override(BASE_CR_STATUS, override, NOW)
        entry = merged["topology"]["hcpSnapshot"][0]
        self.assertEqual(entry["observedAt"], "2026-10-31T11:30:00Z")
        self.assertEqual(entry["hcTier"], "non-prod")
        self.assertEqual(merged["clusterID"], BASE_CR_STATUS["clusterID"])

    def test_marker_inside_hardcoded_shape_not_resolved(self):
        """Only override values resolve — the base is already literal."""
        # (The base carries no markers today; this pins the contract that
        # resolution applies to the override, keeping the base fast-path.)
        override = {"clusterVersion": "now-1h"}
        merged = apply_manifest_cr_status_override(BASE_CR_STATUS, override, NOW)
        self.assertEqual(merged["clusterVersion"], "2026-10-31T11:00:00Z")


if __name__ == "__main__":
    unittest.main()


class ManifestOverrideIntegrationTest(TestCase):
    """End to end: the override rides ocp_create_report into manifest.json.

    Uses the insights-upload directory route (the fixture workflow): the
    payload extracts into the directory with manifest.json beside the
    CSVs — the exact shape robne's csv.Load consumes.
    """

    def _run_report(self, static_report_data):
        """Run ocp_create_report; return the payload dir's manifest.json."""
        import json
        import os
        import tempfile

        from nise.report import ocp_create_report

        with tempfile.TemporaryDirectory() as tmpdir:
            payload_dir = os.path.join(tmpdir, "payload")
            os.mkdir(payload_dir)
            prev_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                options = {
                    "start_date": datetime(2026, 5, 1),
                    "end_date": datetime(2026, 5, 2),
                    "ocp_cluster_id": "test-hcp-cluster",
                    "ros_ocp_info": True,
                    "insights_upload": payload_dir,
                    "static_report_data": static_report_data,
                    "row_limit": 100000,
                    "write_monthly": True,
                }
                ocp_create_report(options)
            finally:
                os.chdir(prev_cwd)
            # The extract route nests the payload under
            # {cluster_id}/{month-range}/ — locate the manifest.
            manifests = [
                os.path.join(root, "manifest.json")
                for root, _, files in os.walk(payload_dir)
                if "manifest.json" in files
            ]
            self.assertTrue(manifests, "payload extraction must produce manifest.json")
            with open(manifests[0]) as handle:
                return json.load(handle)

    def test_override_reaches_manifest_json(self):
        """A template's manifest.cr_status lands in the payload manifest."""
        static = {
            "generators": [
                {"OCPGenerator": {"start_date": "2026-05-01", "end_date": "2026-05-02", "hcp_capacity": {}}}
            ],
            "manifest": {
                "cr_status": {
                    "topology": {
                        "hostedControlPlaneNamespaces": ["clusters-hc9"],
                        "hcpSnapshot": [
                            {
                                "hcpNamespace": "clusters-hc9",
                                "hostedClusterID": "bbbbbbbb-1111-1111-1111-111111111111",
                                "hcUID": "uid-hc-1",
                                "observedAt": "now-30m",
                                "complete": True,
                                "hcTier": "non-prod",
                            }
                        ],
                    }
                }
            },
        }
        manifest = self._run_report(static)
        cr_status = manifest["cr_status"]
        # The override landed.
        entry = cr_status["topology"]["hcpSnapshot"][0]
        self.assertEqual(entry["hcTier"], "non-prod")
        self.assertEqual(entry["hostedClusterID"], "bbbbbbbb-1111-1111-1111-111111111111")
        self.assertIs(entry["complete"], True)
        # The marker resolved against the generation clock: ~30m ago.
        observed = datetime.strptime(entry["observedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        expected = datetime.now(UTC) - timedelta(minutes=30)
        self.assertLess(abs((observed - expected).total_seconds()), 300)
        # The hardcoded defaults survived the merge.
        self.assertEqual(cr_status["clusterID"], "4e009161-4f40-42c8-877c-3e59f6baea3d")
        self.assertIn("authentication", cr_status)

    def test_no_override_manifest_has_no_topology(self):
        """A template without a manifest block produces today's manifest."""
        static = {
            "generators": [
                {"OCPGenerator": {"start_date": "2026-05-01", "end_date": "2026-05-02", "hcp_capacity": {}}}
            ],
        }
        manifest = self._run_report(static)
        self.assertNotIn("topology", manifest["cr_status"])
        self.assertEqual(manifest["cr_status"]["clusterID"], "4e009161-4f40-42c8-877c-3e59f6baea3d")
