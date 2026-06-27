# MCP JSON import and status diagnostics spike

This implements the first low-risk part of the Continue MCP UX steal: import existing ecosystem `.mcp.json` blocks and show better local diagnostics before connecting.

## Implemented

### `.mcp.json` import helpers

Code: `hermes_cli.mcp_config`

- `load_mcp_json_import(path)`
- `import_mcp_json_config(path, write=False, force=False)`
- CLI parser route: `hermes mcp import <path> [--write] [--force]`

Default is dry-run. `--write` persists into `config.yaml` under `mcp_servers`. Existing servers are skipped unless `--force` is passed.

Supported imported keys:

- `command`, `args`, `env`
- `url`, `headers`
- `enabled`
- `timeout`, `connect_timeout`
- `supports_parallel_tool_calls`
- `tools`
- `auth`, `sampling`
- `ssl_verify`, `client_cert`, `client_key`

Unsupported keys are dropped with warnings.

### Secret warnings

Literal `env` and `headers` values are flagged:

```text
env.GITHUB_TOKEN contains a literal value; prefer ${ENV_VAR} placeholders
headers.Authorization contains a literal value; prefer ${ENV_VAR} placeholders
```

This keeps imported config from silently baking secrets into YAML.

### Verbose non-connecting status

Code: `describe_mcp_server_status` and `hermes mcp status` route.

It reports:

- server name
- transport: `stdio`, `http/sse`, or `unknown`
- source: currently `config.yaml`
- enabled/disabled
- tool policy: all / N included / N excluded
- resources flag
- prompts flag
- validation errors
- executable hints for missing `npx`, `node`, `uv`, `uvx`, etc.

## Intentional boundaries

- No project-local `.hermes/mcpServers/` discovery yet.
- No auto-loading repo-provided commands.
- No connection attempt in `status`; this is safe diagnostics only.
- No secrets are copied to `.env` by import; imported values are preserved only if the operator explicitly uses `--write`.
- No runtime MCP resources/prompts remapping yet; this just improves config import and visibility.

## Why this is the first MCP slice

Continue's MCP pattern is useful because it treats MCP as cross-agent, project-local configuration. The safest Hermes entry point is import/status UX before project-local discovery:

1. Users can import known `.mcp.json` files without hand-translating them.
2. Dry-run shows exactly what would be imported.
3. Status reveals risky/missing setup without starting untrusted commands.
4. Project-local discovery can later reuse the same normalization and diagnostics.
