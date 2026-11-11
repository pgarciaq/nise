# #830 Nise Same-Named PVC Lookup — Implementation Plan

> **For agentic workers:** superpowers:test-driven-development governs every step.
> Owner approved the mechanism 2026-11-11: qualify the claim scan by the
> claim's own namespace — continue scanning on mismatch. The intra-
> namespace same-named-claim-on-two-volumes ambiguity is a residual,
> filed as #837 with owner approval, NOT fixed here.

**Repo:** nise, branch `pgarciaq-rosocp-superpowers-phase17`, HEAD
`0a12a20` (the issue's pinned commit; clean tree; pushed to the fork).
Tracked centrally as pgarciaq/ros-ocp-backend#830.

**Recon facts (all verified in code):**
- `get_specific_pvc_from_pod` (ocp_generator.py:1862–1870) resolves the
  pod through the #775-qualified `pod_pvc_map` to a claim NAME, then
  scans `self.volumes` matching `vol["volume_claims"].get(pvc)` by name
  only — first same-named claim wins regardless of namespace (V16-06).
- Both claim-generation paths namespace-stamp every claim dict: the
  static-YAML path (#774, ~line 1785) and the random path (~1835). The
  scan ignores the stamp; the fix reads it.
- Single consumer chain: `get_specific_pvc_from_pod` ← `get_vm_disk`
  (two call sites, both pass `namespace`). Fixing the lookup fixes the
  VM-disk consumer — the close criteria's "through the lookup and its
  VM disk consumer".
- The #775 test (tests/test_ocp_generator.py:567+) asserts namespace
  attribution with DISTINCT claim names — cannot see the same-name
  collision; it stays as the control.
- Test runner: `uv run --frozen python -m unittest` (pytest not in the
  venv). Nise has no CHANGELOG (verify).

**Mechanism:**
```python
for volume in self.volumes:
    for vol_name, vol in volume.items():
        if (specific_pvc := vol["volume_claims"].get(pvc)) and specific_pvc["namespace"] == namespace:
            return pvc, specific_pvc
```
A name match in the wrong namespace is skipped, not returned; the scan
continues until the requested namespace's claim is found. No structural
change; `pod_pvc_map` untouched (its shape feeds the #821-adjacent
membership check — #837's territory).

**Tests:**
- RED: the issue's Appendix E as a unittest — namespaces a/b, pod `web`
  each, claim `data` each (1 GiB / 5 GiB, distinct PV names), BOTH
  declaration orders; assert claim namespace + capacity through
  `get_specific_pvc_from_pod` AND `get_vm_disk` (vc_capacity). Baseline:
  the first namespace's claim wins both lookups, order-flippable.
- Controls: the #775 test green (distinct names, same pod names);
  extend `_same_named_pod_attributes` or add a sibling with the
  same-name shape; pod-without-PVC → ("", {}); `get_vm_disk` no-PVC
  fallback unchanged; static-report path unchanged.
- Mutations: namespace check removed (name-only scan restored) → RED
  fails; return-on-first-name-match regardless of namespace → the
  both-orders assertions catch the order dependence.

**Non-goals:** #837's intra-namespace volume ambiguity; #821's
same-named VMs; no generator rewrite; no CSV schema change (only
attribution values are corrected — zero koku/ros-ocp-backend impact).
