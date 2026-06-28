# mini-swe-agent/Terminal-Bench/Langfuse mining: eval and observability

Sources inspected:

| Source | Evidence |
|---|---|
| mini-swe-agent search result | linear trajectory: every step appends to messages; no difference between trajectory and LM messages |
| Terminal-Bench search result | terminal tasks run in realistic environments with datasets, agents, models, concurrency and result records |
| Existing Hermes/AW Lite workflow | AW Lite already records tasks, evidence, commits and verification; missing piece is a small local eval vocabulary |

## What to steal

The useful primitive is **linear, auditable trajectory + explicit grading**:

1. every agent step appends to a trajectory;
2. verification checks are first-class objects;
3. pass/fail is computed from checks, not confidence;
4. trajectories remain local/private unless explicitly exported;
5. benchmarks are separate from production workflow.

## Hermes/AW Lite translation

| Pattern | Hermes translation |
|---|---|
| mini-swe-agent linear history | Append-only `TrajectoryEvent` model for local eval harnesses |
| Terminal-Bench task grading | `EvalCheck` + `EvalVerdict` with explicit failed checks |
| Langfuse-style traces | Future optional spans/costs, but local/private by default |
| SWE-bench style tasks | AW Lite tasks already provide durable task/evidence units |

## Implemented slice

Added `agent.eval_trajectory`:

- `TrajectoryEventKind`: user/assistant/tool/verify/decision;
- `TrajectoryEvent` append-only event record;
- `append_event(...)` that returns a new tuple without rewriting history;
- `EvalCheck` and `grade_checks(...)`;
- `EvalVerdict` with pass flag, score and failed check names.

This is deliberately small. It gives future agent-quality work a measurable contract without adding telemetry, dashboards or external dependencies.

## Policy

| Situation | Decision |
|---|---|
| no checks | fail, score 0 |
| some checks fail | fail with failed check names |
| all checks pass | pass, score 1 |
| trace export | local only unless explicit opt-in |

## What not to copy

- public telemetry by default;
- benchmark score claims without reproducing the harness;
- treating a trajectory as user-facing proof unless checks pass;
- external dashboards before local evidence is useful.

## Future follow-up

- Add a tiny local eval runner for one Hermes primitive at a time.
- Record AW Lite finish mini-gates as `EvalCheck`s.
- Add private cost/latency spans only if a local operator report needs them.
