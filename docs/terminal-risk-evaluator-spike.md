# Terminal command risk evaluator spike

`tools.terminal_risk` is a Continue-inspired tightening layer for Hermes terminal approvals.

## Implemented in this spike

- `evaluate_terminal_command_risk(command) -> TerminalRiskResult`
- Policies:
  - `safe`
  - `ask`
  - `block`
- Conservative handling for:
  - multiline commands;
  - command chains and pipes;
  - variable and command substitution;
  - parser failures;
  - recursive force removal;
  - raw device overwrites;
  - writes to sensitive paths;
  - in-place edits and git destructive-ish operations.

## Integration proposal

This module should sit in front of the existing `tools.approval` path as a *narrowing* layer only:

```text
existing_approval_policy = current Hermes manual/smart/off/session-yolo decision
risk = evaluate_terminal_command_risk(command)

if risk.policy == block:
    deny even when yolo/off would otherwise pass, for hardline unrecoverable cases
elif risk.policy == ask:
    require approval unless the existing policy already requires a stricter denial
elif risk.policy == safe:
    leave existing Hermes approval behavior unchanged
```

Important: `safe` must not mean auto-approve. It means “this spike found no additional risk.” Existing Hermes approval mode remains authoritative.

## Why this shape

Continue's useful lesson is not its exact blocklist; it is the call-specific evaluator hook:

```text
base tool policy + parsed args -> final policy
```

Hermes already has a mature approval system in `tools.approval`. This spike preserves that system and adds a reusable risk classifier that can be tested independently before any runtime hook is wired.

## Safety boundaries

- Do not weaken `approvals.mode=manual`.
- Do not make `approvals.mode=off` mean unrestricted host destruction for hardline cases.
- Do not depend only on regex for command boundaries; this spike uses `shlex` plus explicit command separators.
- Parser failure is `ask`, never `safe`.
- Variable/subshell expansion is at least `ask`.

## Current verification

- `tests/tools/test_terminal_risk.py`
- `git diff --check`
- Existing selected gateway regression suite from the AW Lite task.
