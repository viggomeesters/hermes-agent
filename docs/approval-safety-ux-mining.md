# Cline/Codex mining: approval and visible tool-diff UX

Sources inspected:

| Source | Evidence |
|---|---|
| `cline/cline` | local clone `/tmp/cline-inspect`, commit `c7de31a`; searched approval/diff/autoApprove surfaces; inspected plan→act wording and MCP autoApprove settings |
| `openai/codex` | local clone `/tmp/codex-inspect`, commit `bdd282f`; inspected `codex-rs/protocol/src/request_permissions.rs` and sandbox/approval docs |
| Codex docs | `https://developers.openai.com/codex/agent-approvals-security`, `https://developers.openai.com/codex/concepts/sandboxing` |

## What to steal

Cline and Codex separate three ideas that Hermes should keep distinct:

1. **mode**: what kind of work is the agent allowed to do now;
2. **surface**: how the pending action is shown to the user/operator;
3. **enforcement**: what the runtime technically allows or blocks.

A good approval system is not just "ask more". It is:

- read-only planning that cannot silently switch into execution;
- workspace writes that show diffs before or as they happen;
- network/MCP writes that request explicit approval;
- destructive/public/payment actions gated to a ship-level mode;
- sandbox boundaries that catch mistakes even when the model is overconfident.

## Evidence patterns

| Pattern | Source evidence | Hermes translation |
|---|---|---|
| Plan/Act separation | Cline SDK text says switching from plan to act must only happen after explicit user approval | `reflect`/`plan` stay read-only; `go` can write in scope; `ship` gates public/destructive/payment |
| Visible file changes | Cline UX surfaces diffs for edits; public docs and examples emphasize approval around diffs | Hermes should classify writes as `SHOW` when a visible diff exists and `ASK` when no diff exists |
| Sandbox vs approval | Codex docs distinguish technical sandbox from approval policy | Hermes approval surfaces should not pretend to enforce OS isolation; they describe the UX layer above existing tool/sandbox enforcement |
| Permission grants | Codex `RequestPermissionsResponse` includes turn/session scope and strict auto-review | Future Hermes grants should be scoped, not global forever; strict-review can apply per turn |
| Destructive MCP calls | Codex docs require approval when tools advertise destructive side effects | MCP write/delete/admin/public/payment actions must never auto-run |

## Implemented slice

Added `agent.approval_surface`, a small deterministic classifier:

- modes: `reflect`, `plan`, `go`, `ship`;
- actions: read, write, execute, network, MCP read/write, public, payment, destructive;
- decisions: `allow`, `show`, `ask`, `block`;
- properties: `visible_diff_required`, `explicit_user_approval_required`.

This is intentionally a **surface classifier**, not enforcement. Existing terminal approvals, tool checks, and future sandbox/runtime gates remain the enforcement layer.

## Policy mapping

| Mode | Read | Workspace write with diff | Command | Network/MCP write | Public/payment/destructive |
|---|---|---|---|---|---|
| reflect | allow | block | block | block | block |
| plan | allow | block | block | block | block |
| go | allow | show | show | ask | block |
| ship | allow | show | show | ask | ask |

## What not to copy

- Cline's VS Code UI internals;
- broad YOLO/autoApprove defaults;
- treating approval prompts as a replacement for sandboxing;
- permanent global grants without scope/expiry;
- public/payment/destructive actions in normal `go` mode.

## Future follow-up

- Wire this classifier into terminal/file/MCP previews where it does not break prompt caching.
- Add a Telegram-friendly compact surface: `SHOW diff`, `ASK network`, `BLOCK destructive outside ship`.
- Add turn/session-scoped approval grants only if there is a clear operator UX and audit trail.
