---
title: "Incident: Codex provider failures after gateway restart"
date: 2026-09-04
status: resolved-in-code
---

# Incident report — Codex provider failures after gateway restart

## Executive summary

On **September 4, 2026**, a Hermes gateway configuration reload caused a restart while four agents were still active. The drain deadline expired, those agents were terminated, and the new gateway process auto-resumed several large conversations at nearly the same time.

The resumed conversations reached the OpenAI Codex backend, but a subset did not receive a first stream event before Hermes' no-byte time-to-first-byte (TTFB) watchdog expired. Hermes retried each affected call. Thirteen sessions recorded at least one failed provider attempt; three Telegram sessions exhausted all three attempts and received the generic user-facing message `The model provider failed after retries`.

This was **not caused by a Hermes version upgrade going live**. The production service was still running the `v0.19.1` overlay plus 42 local carries. The prepared `v0.21.0` quality candidate had not been switched into production. However, both versions contained the same contradictory TTFB behavior, so promoting the candidate without this fix would have preserved the failure mode.

One diagnostic trap initially suggested otherwise: `gateway_state.json` still contained `code_version: 0.21.0` and the SHA from a September 2 staging rehearsal. The rehearsal was rolled back, but the older runtime did not remove those newer, unknown fields when it later rewrote the same status file. The active process path, editable-install metadata, Git reflog at the process start time, and imported CLI version all identify the September 4 runtime as `0.19.1`.

## Impact

- Window investigated: **07:43–08:44 CEST** on September 4, 2026.
- Four active agents exceeded the 180-second shutdown drain and were terminated.
- Multiple large sessions were auto-resumed immediately after startup.
- Thirteen sessions had at least one provider-attempt failure in the investigated burst.
- Three Telegram sessions exhausted three retries and surfaced the generic provider-failure message.
- No evidence of invalid credentials, exhausted quota, HTTP 429 rate limiting, or a Hermes queue overflow was found in the terminal failures.
- Raw provider responses and credentials are intentionally excluded from this report.

## Timeline

| Time (CEST) | Event |
|---|---|
| 07:43:41 | Gateway received a stop/reload request after configuration work. |
| 07:46:41 | The 180-second drain deadline expired with four agents still active; they were terminated. |
| 07:46:47 | Gateway restarted from the same live source checkout and began auto-resuming conversations. |
| 07:59 onward | Resumed/active sessions began recording no-first-byte provider failures and retries. |
| 08:06–08:18 | Three Telegram sessions exhausted all three attempts and received the generic failure message. |
| 08:18–08:44 | Additional attempts hit no-first-byte timeouts, but no additional session exhausted all retries. |

## Technical root cause

Hermes estimates request context size and gives very large Codex requests a longer no-byte TTFB budget. For requests above 100,000 estimated tokens, the adaptive budget is 180 seconds.

The resolver then applied `HERMES_CODEX_TTFB_MAX_SECONDS` with an **implicit default of 120 seconds**. That silently reduced the 180-second large-context budget back to 120 seconds. In other words, the code scaled the timeout up and immediately capped it down again.

The forced restart created the trigger conditions:

1. active conversations were interrupted;
2. several large contexts resumed in a burst;
3. the backend took longer than usual to emit a first stream event;
4. Hermes killed attempts at the contradictory 120-second ceiling;
5. three sessions repeated that outcome three times and surfaced the terminal error.

The provider's latency was a contributing condition, but the local watchdog contradiction amplified a recoverable slow start into user-visible failures.

## Why this was not a concurrency-limit failure

The live provider queue was configured with a maximum of three concurrent OpenAI Codex calls. Logs showed queue admission and release operating at or below that limit. The terminal errors were no-byte TTFB timeouts, not local `concurrency_limit`, HTTP 429, quota, or authentication errors.

## Fix

The TTFB calculation is now isolated in `_resolve_codex_ttfb_watchdog` and follows this policy:

- the standard no-byte TTFB base remains 120 seconds;
- context-size scaling remains active for large Codex requests;
- an **unset** `HERMES_CODEX_TTFB_MAX_SECONDS` no longer imposes a hidden 120-second cap;
- a positive, explicitly configured maximum is still honored as an operator override;
- `HERMES_CODEX_TTFB_TIMEOUT_SECONDS=0` still disables the TTFB watchdog;
- the separate finite hard timeout remains in place to reclaim genuinely wedged requests.

Regression tests cover both the uncapped >100k-token default (180 seconds) and an explicit 90-second operator cap.

## Upgrade status

As of **September 4, 2026**:

- live source at incident start: `v0.19.1` overlay plus 42 local carries;
- current checkout after workflow-runtime bookkeeping: still `v0.19.1`, now plus 43 local carries; this is not a Hermes release cutover;
- live Hermes runtime version: `0.19.1`;
- prepared candidate: `quality/v0.21.0-bertus-20260902-r2` at commit `500b1a3f5410`;
- candidate verification: 548 tests passed, zero failed;
- production source switch/restart: **not performed**;
- reason for hold: the candidate was intentionally staged but production cutover remained blocked on concurrent runtime drift;
- a temporary staging rehearsal started candidate code on September 2 and then rolled it back; stale `code_version`/`code_sha` fields survived in `gateway_state.json` and are not proof of the current loaded runtime;
- this TTFB defect was present in both live and candidate code.

At the time of the original incident analysis on September 4, 2026, the answer to “was the Hermes update finally applied?” was **no**: it had been prepared and tested but not loaded in production. That changed with the verified gateway cutover later the same day; the evidence below records the post-cutover state.

## Verification results — September 4, 2026

- Focused and broader provider regression command:
  `venv/bin/python -m pytest tests/agent/test_codex_ttfb_watchdog.py tests/run_agent/test_provider_fallback.py -q -o 'addopts='`
  → **28 passed**.
- `git diff --check ad3c90d091^ ad3c90d091` → passed.
- Repo-local workflow readiness: stack `v0.3.14`, exact pinned ref, doctor `ready=true`, contract valid.
- `hermes doctor` → config version 33 current, OpenAI Codex authenticated, required packages and gateway service prerequisites available. The reported state-DB diagnostic timeout and frontend dependency advisories are separate maintenance findings, not provider-connectivity failures.
- Two real configured-provider probes were run with fallback disabled and the prompt `Reply exactly: PROVIDER_PROBE_OK`:
  - probe 1: exact response, one `openai-codex/gpt-5.6-sol` API call, 9 seconds;
  - probe 2: exact response, one `openai-codex/gpt-5.6-sol` API call, 8 seconds.
- Loaded runtime proof: `hermes-gateway.service` is `active/running`; PID `3206546` started at `2026-09-04 17:58:25 CEST` from `/home/viggo/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main gateway run`. The source checkout contains provider fix `ad3c90d091` and was at `45ed8d2500` for the final runtime readback.
- Live Telegram document smokes through that loaded adapter succeeded as message IDs `72771` and `72772`; no fallback-success ambiguity remained.

These results supersede the earlier staged-only status above: the provider fix is now present in the loaded gateway source and direct no-fallback Codex calls complete successfully.

## Follow-up

- Keep runtime restarts drain-aware; avoid configuration reloads while long agents are active when possible.
- Preserve the fail-closed fallback policy: do not hide this class of failure behind an untrusted small local model.
- When the `v0.21.0` candidate is promoted, verify that this fix is present in the exact source commit used by the service.
- Use the provider troubleshooting guide for future failures instead of diagnosing from the generic chat message alone.
