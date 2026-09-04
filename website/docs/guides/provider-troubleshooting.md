---
sidebar_position: 13
title: "Provider Troubleshooting"
description: "Diagnose Hermes model-provider failures, retries, authentication errors, rate limits, timeouts, and fallback problems without exposing secrets"
---

# Provider Troubleshooting

Hermes deliberately keeps raw provider details out of chat messages. A message such as `The model provider failed after retries` tells you the retry policy was exhausted; it does **not** identify the underlying cause. Diagnose the first failed attempt in local logs before changing models, credentials, or timeout settings.

## Safe first checks

```bash
hermes status
hermes doctor
hermes auth list
```

For a gateway service on Linux:

```bash
systemctl --user status hermes-gateway.service --no-pager
journalctl --user -u hermes-gateway.service --since "30 minutes ago" --no-pager
```

Hermes log files normally live under `$HERMES_HOME/logs/` (usually `~/.hermes/logs/`). Search locally, but do not paste credentials, OAuth tokens, request bodies, or raw provider responses into public issues or chats.

```bash
grep -Ei 'provider|retry|rate.?limit|quota|unauthorized|forbidden|timed out|no bytes|stale|circuit' \
  ~/.hermes/logs/errors.log ~/.hermes/logs/gateway.log | tail -200
```

## Common failure matrix

| Chat symptom or log signature | Likely cause | Check | Correct action |
|---|---|---|---|
| `The model provider failed after retries` | Wrapper message; the real cause is earlier in the logs | Inspect the first exception for that session and timestamp | Fix the typed root cause below; do not keep retrying blindly |
| HTTP `401`, `invalid_grant`, revoked/expired token | OAuth or API credential is no longer valid | `hermes auth list`; inspect provider-specific auth status | Re-authenticate with `hermes auth add <provider>` or `hermes model`; never copy tokens into chat |
| HTTP `403` / forbidden | Account, organization, model, region, or policy lacks access | Verify selected model and provider account entitlements | Select an allowed model/account or correct provider permissions |
| HTTP `429`, quota exhausted, rate limit | Provider-side quota or request-rate limit | Check provider dashboard and retry headers; compare concurrent sessions | Wait for reset, reduce concurrency, or configure a trusted fallback with independent credentials |
| `concurrency_limit` / queued provider call | Hermes' local provider queue is full | Check gateway queue logs and `providers.concurrency` | Let queued work drain or raise the limit only if the account/provider can sustain it |
| HTTP `500`, `502`, `503`, `service unavailable`, circuit open | Provider or upstream gateway outage | Try a small direct probe and check provider status | Wait, use a trusted independent fallback, or switch provider; local restarts rarely fix an upstream outage |
| `no bytes within TTFB cutoff` | Connection opened but no first stream event arrived in time | Note context size, timeout, restart/resume burst, and whether retries all hit the same boundary | Upgrade to a build with adaptive Codex TTFB handling; avoid an accidental low max cap |
| `after first byte` / stream idle timeout | Stream started and then stopped producing events | Compare last-event time and configured stale timeout | Retry; if persistent, inspect transport/provider health before extending the timeout |
| `stale_call_kill` / non-streaming call stale | Non-streaming request exceeded its context-aware stale timeout | Inspect model, context estimate, and endpoint health | Fix endpoint slowness or tune the relevant stale timeout; keep a finite hard ceiling |
| `tool_call` without matching `tool_result` or provider HTTP `400` after tools | Conversation history integrity was broken | Inspect session history around interrupted tool calls | Use a build with tool-pair repair; if the stored history is already corrupt, start a clean session after preserving needed context |
| Image/request too large, too many images, payload limit | Vision payload exceeds provider or transport limits | Count images and inspect compressed dimensions/bytes | Reduce, resize, or split image batches |
| Fallback fails immediately with `401` | Stale key on the fallback provider | Inspect fallback chain and credential source | Repair/remove that fallback; a broken fallback only adds latency and noise |
| Telegram/Discord delivery error after a successful model call | Messaging transport failure, not a model-provider failure | Look for successful agent completion followed by platform API error | Fix bot token, chat permissions, network, or delivery target |

## Codex no-first-byte timeouts

OpenAI Codex requests use a no-byte TTFB watchdog so a dead connection does not hang for the full HTTP read timeout. Large contexts can legitimately spend longer in admission or prompt prefill, so current Hermes builds scale this budget with estimated context size.

Relevant environment variables:

| Variable | Meaning |
|---|---|
| `HERMES_CODEX_TTFB_TIMEOUT_SECONDS` | Base no-first-byte timeout. `0` disables this watchdog. |
| `HERMES_CODEX_TTFB_DISABLE_ABOVE_TOKENS` | Context threshold above which adaptive patience applies unless strict mode is enabled. |
| `HERMES_CODEX_TTFB_STRICT=1` | Keep the smaller configured base instead of scaling it for large contexts. |
| `HERMES_CODEX_TTFB_MAX_SECONDS` | Optional explicit maximum. Unset/`0` means no extra cap; the adaptive timeout remains authoritative. |
| `HERMES_CODEX_EVENT_STALE_TIMEOUT_SECONDS` | Maximum idle gap after at least one Codex stream event. |
| `HERMES_CODEX_HARD_TIMEOUT_SECONDS` | Finite total-request backstop for genuinely wedged calls. |

Do not solve a slow large-context request by setting every timeout to infinity. That replaces visible failures with invisible stuck agents. Keep the hard timeout finite and adjust only the watchdog proven by the logs.

## Distinguish a restart from an upgrade

A gateway restart can happen after configuration changes without changing the Hermes source version. Check all three separately:

```bash
hermes --version
systemctl --user show hermes-gateway.service -p MainPID -p ExecStart --no-pager
git -C /path/to/hermes-agent rev-parse --short HEAD
```

- **Version**: package/runtime version reported by Hermes.
- **Source commit**: checkout actually imported by the service process.
- **Restart time**: process lifecycle event; not proof of an upgrade.

A staged branch, downloaded tag, or green candidate test report is not live until the service's source path/commit is switched and the process is restarted successfully.

Treat persisted `code_version` or `code_sha` fields as evidence, not absolute truth. A rollback to an older runtime can leave newer fields behind if that runtime does not know how to clear them. Corroborate status JSON with the active process start time, import path, package/editable-install metadata, Git reflog, and startup logs.

## Fallback rules

Fallbacks help only when they are independent and trustworthy:

- use a different provider account or transport, not the same exhausted credential under another name;
- verify every fallback credential before adding it to production;
- do not silently fall back to a small local model for high-stakes or tool-using sessions;
- preserve the original error in local logs so a successful fallback does not erase the incident signal.

## When reporting an incident

Include:

- exact timestamps and timezone;
- Hermes version, source commit, and whether a restart or upgrade occurred;
- provider/model names but **no credentials**;
- number of affected attempts and terminally failed sessions;
- first typed exception, retry count, context estimate, and timeout boundary;
- whether a minimal direct provider probe succeeds;
- whether the same failure reproduces after the queue drains.

This is enough to separate provider outage, authentication, local queue pressure, request-integrity bugs, and watchdog misconfiguration without leaking raw provider data.
