# #832 Nise TLS Override — Implementation Plan

> **For agentic workers:** superpowers:test-driven-development governs every step.
> Owner approved approach (a) 2026-11-11: make the REQUESTS_VERIFY override
> FUNCTIONAL — one helper, default TRUE (verified), applied at ALL FOUR
> egress points; the warning stays (now true); the false "requests honors
> natively" comment corrected. No weakening of defaults; private-CA
> (REQUESTS_CA_BUNDLE, which Requests DOES honor natively) untouched.

**Repo:** nise, branch `pgarciaq-rosocp-superpowers-phase17`, HEAD `ef7d26d`
(report.py unchanged since the issue's pinned `0a12a20118e2` — the region
is identical). Tracked as pgarciaq/ros-ocp-backend#832 (V16-07, P3).

**Recon facts (verified):**
- The warning fires on REQUESTS_VERIFY ∈ {false, 0, no} but none of the
  requests.post calls pass `verify`; Requests implements no such env var.
- FOUR egress points: the HCC token acquisition (report.py:356) plus the
  three upload calls (identity_header / basic_auth / bearer_token). The
  override must cover all four — in the self-signed-ingress lab scenario
  the token endpoint fails TLS first otherwise, making the knob unusable.
- Auth method selection: INSIGHTS_ACCOUNT_ID+INSIGHTS_ORG_ID →
  identity_header; INSIGHTS_USER+INSIGHTS_PASSWORD → basic_auth; else →
  bearer_token (token acquisition first).

**Mechanism:**
- `_requests_verify() -> bool`: reads REQUESTS_VERIFY, false-ish set
  {false, 0, no}, default True — ONE definition shared by the warning
  and every call site, so the diagnostic and the transport cannot
  disagree.
- `verify=_requests_verify()` on all four requests.post calls.
- The #755 comment corrected: requests does NOT honor REQUESTS_VERIFY
  (only REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE for the bundle); nise
  implements the opt-in itself, verified by default.

**Tests (the close criteria demand the transport boundary, not warning
strings):**
- RED: the issue's Appendix F as a unittest — patch
  requests.adapters.HTTPAdapter.send, REQUESTS_VERIFY=false, dummy
  basic credentials, the real uploader; assert the adapter received
  verify=False AND the warning fired. Baseline: verify=True (defect).
- Per-auth-method matrix: identity_header, basic_auth, bearer_token
  each asserted at the boundary (a missed call site is a silent partial
  override). Bearer also asserts the TOKEN acquisition call carries
  verify=False.
- Controls: no env → verify=True, no warning; REQUESTS_VERIFY=true →
  verify=True, no warning.
- Mutations: one call site hardcoded verify=True → its per-method test
  fails; warning removed → the warning assertion fails; helper inverted
  → the controls fail.

**Non-goals:** no default weakening; no dependency/CVE attestation; no
real credentials; no cross-repo impact (a nise-side lab knob only).
