# OpenHands/SWE-agent mining: sandboxed durable execution

Sources inspected:

| Source | Evidence |
|---|---|
| `All-Hands-AI/OpenHands` | local clone `/tmp/openhands-inspect`, commit `de4e2eb`; repository now emphasizes app/server/sandbox directories and hosted/agent-canvas runtime surfaces |
| OpenHands runtime docs | `https://docs.openhands.dev/openhands/usage/architecture/runtime` |
| OpenHands README/search result | Docker/project mount flow and agent workspace model |
| SWE-agent family | Used as comparison class for benchmark/task lifecycle patterns; not cloned in this slice |

## What to steal

OpenHands is useful for Hermes/AW Lite mainly because it treats autonomous coding as a **runtime boundary problem**, not just a prompt problem.

The transferable pattern:

1. user intent becomes a task/conversation;
2. task runs in a bounded workspace/runtime;
3. actions are executed by an action server/client boundary;
4. each action returns an observation;
5. durable state/evidence survives the individual model turn;
6. network/secrets/sandbox are explicit runtime policy, not implicit trust.

## Hermes/AW Lite translation

| OpenHands pattern | Hermes/AW Lite equivalent |
|---|---|
| Docker/runtime sandbox | Future sandbox profile for untrusted code or secret/public-side-effect work |
| Action execution server | Existing tool calls plus future boundary metadata; do not add a separate runner unless needed |
| Observations | Tool outputs + AW Lite evidence + repo commits |
| Conversation/task state | AW Lite parent plan/task YAML and pushed commits |
| Runtime image/source tags | Future reproducible environment hash or workspace manifest |
| Network/secrets control | Default network-off for risky sandboxes; secrets only in setup/wrapper phase, never in task YAML |

## Implemented slice

Added `agent.execution_boundary`:

- `ExecutionBoundary`: `in_process`, `background_process`, `durable_workflow`, `sandbox_required`;
- `WorkloadRisk`: low/medium/high;
- `classify_execution_boundary(...)` for policy classification.

This primitive helps answer: should this work run in the current Hermes turn, a tracked background process, AW Lite durable workflow state, or a future sandbox?

## Policy outcomes

| Situation | Boundary |
|---|---|
| bounded local read/write | `in_process` |
| long non-repo task | `background_process` with tracked evidence |
| repo-changing long/resumable task | `durable_workflow` via AW Lite |
| untrusted code, secrets, or public side effects | `sandbox_required` |

## What not to copy

- The full OpenHands platform;
- Docker as a mandatory dependency for all Hermes work;
- hidden background autonomy without AW Lite evidence;
- broad host mounts;
- network-on by default;
- secrets available during the agent phase.

## Future follow-up

- Add a `hermes sandbox doctor` or config diagnostic only if a concrete sandbox runner exists.
- For high-risk future GO tasks, record execution profile in AW Lite evidence.
- If sandbox execution becomes real, make network and mount policy visible before the run starts.
