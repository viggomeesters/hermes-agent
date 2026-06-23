# Hermes fork maintenance runbook

This repo is the live Hermes runtime checkout for Bertus. Treat it as a carried
patch stack on top of upstream, not as a place to do blind updates.

## Remotes and branch semantics

- `origin` = read-only upstream source: `NousResearch/hermes-agent`.
- `viggo` = Viggo's fork/push target: `viggomeesters/hermes-agent`.
- `runtime/live-upgrade-20260623` = current live runtime branch in
  `/home/viggo/.hermes/hermes-agent`.
- `viggo/runtime-upgrade-20260623` = pushed staging/runtime branch on the fork.
- `fix/gateway-memory-local-replay` and
  `viggo/snapshot-pre-upstream-sync-20260623-075039` are rollback/protection
  branches from the pre-upgrade runtime.

## Normal maintenance loop

```bash
cd /home/viggo/.hermes/hermes-agent
git fetch origin main
git status --short
git rev-list --left-right --count HEAD...origin/main
python -m pytest tests/gateway/test_busy_session_ack.py tests/gateway/test_display_config.py tests/gateway/test_email.py
git diff --check
hermes --version
systemctl --user is-active hermes-gateway.service hermes-gateway-vrouw.service hermes-dashboard.service
'/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe' -NoProfile -ExecutionPolicy Bypass -File C:/Users/viggo/AppData/Local/BertusQuietMode/verify-bertus-boot-task.ps1
```

Do **not** run `git pull`, rebase, service restart, or release commands from the
watchdog. Upgrade work stays task/plan driven and uses a staging branch first.

## Watchdog

`scripts/hermes_fork_sync_watchdog.py` is a quiet no-op watchdog:

- prints nothing when upstream drift is below threshold and the repo is clean;
- prints an alert when behind count crosses the threshold or dirty files appear;
- never pulls, rebases, checks out, restarts services, or edits files;
- may refresh `origin/main` via `git fetch origin main` unless `--no-fetch` is
  used.

Smoke tests:

```bash
python3 scripts/hermes_fork_sync_watchdog.py --dry-run --no-fetch
python3 scripts/hermes_fork_sync_watchdog.py --dry-run --mock-behind 999 --mock-dirty 2
python3 scripts/hermes_fork_sync_watchdog.py --behind-threshold 9999 --no-dirty-alert --no-fetch
```

Cron pattern for Hermes scheduler (script-only/no-agent):

```text
schedule: every 6h
script: /home/viggo/.hermes/hermes-agent/scripts/hermes_fork_sync_watchdog.py
no_agent: true
```

Empty stdout is the expected green path; Hermes sends nothing when there is no
alert.

## Rollback

Rollback before further maintenance if the live runtime regresses:

```bash
cd /home/viggo/.hermes/hermes-agent
git status --short
git switch fix/gateway-memory-local-replay
systemctl --user restart hermes-gateway.service hermes-gateway-vrouw.service hermes-dashboard.service
systemctl --user is-active hermes-gateway.service hermes-gateway-vrouw.service hermes-dashboard.service
hermes --version
'/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe' -NoProfile -ExecutionPolicy Bypass -File C:/Users/viggo/AppData/Local/BertusQuietMode/verify-bertus-boot-task.ps1
```

Alternative protected snapshot:

```bash
git switch viggo/snapshot-pre-upstream-sync-20260623-075039
```

Keep `hermes-gateway-daily-restart.timer` disabled unless Viggo explicitly asks
to re-enable it.
