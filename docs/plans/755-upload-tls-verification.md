# #755 Nise Upload TLS Verification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nise's credential-carrying upload branches verify server certificates by default — exactly like Koku's own transport layer — with the standard requests env vars (`REQUESTS_CA_BUNDLE`, `REQUESTS_VERIFY`) as the only CA/insecure knobs, and a visible warning when insecure mode is active.

**Architecture:** Delete the two `verify=False` kwargs so requests' default (`True`) applies uniformly across all three auth modes and the token acquisition. No bespoke config: private-CA labs set `REQUESTS_CA_BUNDLE` (requests-native, zero code — the mechanism koku's own tooling relies on); insecure labs set `REQUESTS_VERIFY=false` (requests-native) with one `LOG.warning` from nise at upload start. Koku reference verified: **zero `verify=False` anywhere in koku's masu external code** — requests' default everywhere, no custom CA config in code.

**Tech Stack:** Python 3.11, requests, pytest/tox (`uv-venv-lock-runner`); the existing `@patch("nise.report.requests.post")` test pattern.

**Spec:** [GH #755](https://github.com/pgarciaq/ros-ocp-backend/issues/755) (V15-05, P1) + its handoff comment (verify by default, configured CA, explicit warned opt-in) + owner direction 2026-11-04 (do what Koku does — verified: koku's transport layer has no verify=False and no custom CA surface) + session recon.

**Implementation repository:** `~/dev/koku/nise`, branch `pgarciaq-rosocp-superpowers-phase17` (zero drift from the reviewed baseline `e2e1b9b2` — clean tree verified). #755 is centrally tracked in ros-ocp-backend.

**Recon-verified facts this plan argues from:**

- The two sites: `nise/report.py:376` (basic_auth) and `:384` (bearer_token) — `verify=False` unconditional. Sweep: **exactly two, no others** in nise's non-test code.
- The asymmetry: the `identity_header` branch (`:363-368`) has **no verify kwarg** (requests default `True`); the OAuth token acquisition (`:345`) also verifies. Only the two credential-carrying upload branches disable verification — the token is acquired over a verified connection and then sent over an unverified one.
- Auth modes selected by env presence: `INSIGHTS_ACCOUNT_ID`/`INSIGHTS_ORG_ID` → identity_header; `INSIGHTS_USER`/`INSIGHTS_PASSWORD` → basic_auth; else bearer via `HCC_SERVICE_ACCOUNT_ID`/`HCC_SERVICE_ACCOUNT_SECRET` against `HCC_TOKEN_URL`.
- Existing tests (`nise/tests/test_report.py:376-405`): `@patch.dict(os.environ, ...)` + `@patch("nise.report.requests.post")`, asserting `mock_post.call_args` — the regression pattern extends by asserting the `verify` kwarg.
- Nise implements **no cost-model/price-list functionality** — it is a data generator + uploader; the rate strings in generators are fake CSV content. No other Koku-API surfaces to align.
- Requests env behavior (no code needed): `REQUESTS_CA_BUNDLE=/path/ca.pem` sets the CA bundle; `REQUESTS_VERIFY=false` disables verification session-wide.

## Global Constraints

- The fix lands in **nise**; commits wait for explicit owner go-ahead (repo approval gate). Push target: the nise fork remote on `pgarciaq-rosocp-superpowers-phase17` (confirm the remote name before pushing — nise's origin may point upstream).
- **Default must verify** — no weakening, no lab-convenience default.
- **No bespoke config surface** — koku has none; the requests env vars are the only knobs.
- Preserve non-auth/local generation paths (local-directory uploads, S3/MinIO) untouched.
- No `t.Skip`, no weakened assertions; rules-out comments per adversarial-fixtures discipline.
- Scope: solve the demonstrated case; no drive-by refactors of the retry loop, the token flow, or the generators.

## Review Focus

1. **Both credential branches fixed, uniformly** — basic_auth AND bearer_token assert `verify` absent-or-True; identity_header unchanged (already verified). → Task 2 assertions on all three modes.
2. **The token/upload asymmetry closed** — the bearer flow's upload now matches its token acquisition (verified). → Task 2 bearer test asserts both calls.
3. **Insecure mode is explicit AND warned** — `REQUESTS_VERIFY=false` still functions (requests-native) but nise logs a warning naming the URL. → Task 2 warned-insecure test.
4. **CA bundle pass-through** — `REQUESTS_CA_BUNDLE` reaches requests without nise interference. → Task 2 CA test.
5. **No third site missed** — the sweep is re-run post-implementation; exactly zero `verify=False` remain in non-test nise code. → Task 4.

---

### Task 1: The upload-path warning (self-contained TDD)

**Files:**
- Modify: `nise/nise/report.py` (one `LOG.warning` before the retry loop when `REQUESTS_VERIFY` is falsy)
- Test: extend `nise/tests/test_report.py`

**Interfaces:**
- Produces: a module-level helper `_warn_if_insecure_upload()` (or inline check) reading `REQUESTS_VERIFY` via requests' own resolution — log `"WARNING: TLS certificate verification is DISABLED for uploads (REQUESTS_VERIFY=%s). This exposes credentials to network interception — use only in isolated labs."` when falsy.

- [ ] **Step 1: Write the failing test** — `REQUESTS_VERIFY=false` in the env patch + `assertLogs` capturing the warning; absent when unset or `true`. (Note: requests treats the env var at session/import level — the helper must read the env directly, not depend on requests internals.)
- [ ] **Step 2: Run → RED** (`AssertionError: no logs` — the warning doesn't exist).
- [ ] **Step 3: Implement** — the check + `LOG.warning` at the top of the upload retry block in `ocp_route_file`.
- [ ] **Step 4: Run → GREEN.**

### Task 2: Regression tests — RED on the reviewed baseline

**Files:**
- Modify: `nise/tests/test_report.py` (extend the existing upload tests; add the new cases)

- [ ] **Step 1: Write the failing tests**, per auth mode:
  - **basic_auth**: existing test asserts `mock_post.call_args[1]` — add `self.assertNotIn("verify", kwargs) or self.assertTrue(kwargs.get("verify", True), "...")`: the precise assertion is `kwargs.get("verify", True) is True` (absent = default = verified; present-True = explicit — both pass; present-False fails). **RED on baseline**: `verify=False` is present.
  - **bearer_token**: same assertion on the upload call; PLUS assert the token-acquisition call (`mock_post` first invocation) also verifies — pinning the closed asymmetry. **RED on baseline.**
  - **identity_header**: existing test extended with the same assertion — **passes on baseline** (positive control: the already-correct branch).
  - **Warned insecure**: with `REQUESTS_VERIFY=false` mocked, the upload still proceeds (requests-native) and the warning fired (Task 1).
  - **CA pass-through**: with `REQUESTS_CA_BUNDLE=/tmp/fake-ca.pem` set and requests' session patched (or `requests.Session().verify` inspected), the bundle is honored — nise adds no interference. (Mock-transport level: assert nise passes NO `verify`/`cert` kwargs that would override the env.)
- [ ] **Step 2: Run → RED** for the two credential-mode assertions (the issue's mechanism: `verify=False` present); controls green.
- [ ] **Step 3: Ledger the RED output.**

### Task 3: The fix — delete the two kwargs

**Files:**
- Modify: `nise/nise/report.py:376`, `:384`

- [ ] **Step 1:** Delete `verify=False,` from both branches. Add the one-line comment at each site: `# TLS verified by default (requests); private-CA labs set REQUESTS_CA_BUNDLE (#755)`.
- [ ] **Step 2: Run → GREEN** — all Task 2 tests plus the existing suite (`tox -e 3.11` or the repo's runner).
- [ ] **Step 3: Commit** (after owner go-ahead, in nise): `fix(#755): verify upload TLS by default — private CA via REQUESTS_CA_BUNDLE, warned insecure via REQUESTS_VERIFY`

### Task 4: Sweep + full verification

- [ ] **Step 1: Sweep re-run** — `grep -rn "verify" nise/ --include="*.py" | grep -v test`: zero `verify=False` remain; the only verify references are the warning helper and comments.
- [ ] **Step 2: Mutation** — re-add `verify=False` to ONE branch → its test fails naming the kwarg; restore.
- [ ] **Step 3: Full suite** — the repo's test runner green.
- [ ] **Step 4: Commit any strengthening** (after owner go-ahead).

### Task 5: Lab runbook note + close-out

- [ ] **Step 1:** The SNO lab's nise invocations (self-signed ingress) need `REQUESTS_CA_BUNDLE=/path/to/onprem-ca.pem` — record in the #755 close-out as the deployment note (the runbook edit itself can land with the next lab session; asserted, not applied, unless the owner wants it now).
- [ ] **Step 2: Comment on #755** — the Koku reference (zero verify=False in masu external code), the asymmetry closed, the requests-native design rationale, mutation results, the adversarial answer.
- [ ] **Step 3: Close with the completion-report table** — verified vs asserted (CI on the nise push; live-lab upload not performed — the negative-control criterion is satisfied at the mock-transport level with dummy credentials per the issue's handoff).

---

## Self-review notes

- **Spec coverage:** criterion 1 (verify by default, both modes) → Tasks 2-3; criterion 2 (private CA + explicit warned insecure) → the requests-native design + Task 1's warning + Task 2's cases; criterion 3 (both auth modes + token/upload transport policy, dummy credentials, mock transport) → Task 2; criterion 4 (TLS-invalid negative control without real credentials; non-auth paths preserved) → the mock-level verify assertions + the untouched local/S3 paths (noted); criterion 5 (RED on baseline, right reason, correction) → Tasks 2-4; criteria 6-8 → Tasks 4-5.
- **Proportion:** two kwarg deletions + one warning + test extensions; the smallest P1 fix of the v15 set — the risk was the missing config story, and the Koku reference resolves it to "no new config."
