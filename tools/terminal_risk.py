"""Conservative terminal command risk evaluator.

This module is a Continue-inspired spike that can sit in front of Hermes'
existing approval system as a *tightening* layer. It does not replace
``tools.approval`` and should never auto-approve a command that the existing
approval mode would ask for.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
import shlex


class TerminalRiskPolicy(StrEnum):
    """Risk policy returned by the evaluator."""

    SAFE = "safe"
    ASK = "ask"
    BLOCK = "block"


@dataclass(frozen=True)
class TerminalRiskResult:
    policy: TerminalRiskPolicy
    reasons: tuple[str, ...] = ()

    @property
    def requires_permission(self) -> bool:
        return self.policy in {TerminalRiskPolicy.ASK, TerminalRiskPolicy.BLOCK}


_POLICY_RANK = {
    TerminalRiskPolicy.SAFE: 0,
    TerminalRiskPolicy.ASK: 1,
    TerminalRiskPolicy.BLOCK: 2,
}

_COMMAND_SEPARATORS = {";", "&&", "||", "|"}
_WRAPPER_COMMANDS = {"sudo", "env", "command", "exec", "time", "nohup", "setsid"}
_READ_ONLY_COMMANDS = {
    "cat",
    "cd",
    "date",
    "du",
    "echo",
    "find",
    "git",
    "grep",
    "head",
    "ls",
    "pwd",
    "python",
    "python3",
    "rg",
    "sed",  # only read-only sed; -i is handled below
    "tail",
    "wc",
}

_ALWAYS_ASK_COMMANDS = {
    "bash",
    "bun",
    "curl",
    "docker",
    "gh",
    "make",
    "node",
    "npm",
    "pnpm",
    "python",
    "python3",
    "sh",
    "uv",
    "uvx",
    "wget",
    "yarn",
}

_BLOCK_COMMANDS = {
    "mkfs",
    "reboot",
    "shutdown",
    "halt",
    "poweroff",
}

_WRITE_COMMANDS = {
    "chmod",
    "chown",
    "cp",
    "dd",
    "install",
    "mv",
    "rm",
    "rsync",
    "tee",
    "truncate",
}

_VAR_PATTERN = re.compile(r"(?<!\\)(?:\$\w+|\$\{[^}]+\}|`[^`]+`|\$\()")
_REDIRECT_PATTERN = re.compile(r"(^|\s)(?:>|>>|2>|&>|<>)")
_DANGEROUS_ROOT_PATTERN = re.compile(r"(^|\s)(?:/|/\*|~|\$HOME|\$\{HOME\})(?:\s|$)", re.IGNORECASE)
_SENSITIVE_TARGET_PATTERN = re.compile(
    r"(?:^|\s)(?:/etc/|/private/etc/|/dev/sd|/dev/nvme|~/.ssh|\$HOME/.ssh|\$\{HOME\}/.ssh|~/.hermes/(?:config\.yaml|\.env)|\$HERMES_HOME/(?:config\.yaml|\.env)|\.env(?:\.|\s|$)|config\.yaml(?:\s|$))",
    re.IGNORECASE,
)


def evaluate_terminal_command_risk(command: str | None) -> TerminalRiskResult:
    """Evaluate a terminal command using conservative shell-token heuristics.

    Semantics:
    - empty commands are safe;
    - parser failure returns ask;
    - multiline commands are evaluated line by line;
    - variable/subshell expansion forces at least ask;
    - every command in a pipe/chain is evaluated;
    - the most restrictive policy wins.
    """

    if not command or not str(command).strip():
        return TerminalRiskResult(TerminalRiskPolicy.SAFE)

    combined = TerminalRiskResult(TerminalRiskPolicy.SAFE)
    for line in str(command).splitlines():
        line = line.strip()
        if not line:
            continue
        combined = _most_restrictive(combined, _evaluate_line(line))
        if combined.policy is TerminalRiskPolicy.BLOCK:
            return combined
    return combined


def _evaluate_line(line: str) -> TerminalRiskResult:
    reasons: list[str] = []
    baseline = TerminalRiskPolicy.SAFE

    if _VAR_PATTERN.search(line):
        baseline = TerminalRiskPolicy.ASK
        reasons.append("variable or command substitution requires review")

    if _REDIRECT_PATTERN.search(line):
        baseline = TerminalRiskPolicy.ASK
        reasons.append("shell redirection may write files")

    try:
        tokens = shlex.split(_space_shell_separators(line), posix=True)
    except ValueError as exc:
        return TerminalRiskResult(TerminalRiskPolicy.ASK, (f"shell parse failed: {exc}",))

    current: list[str] = []
    result = TerminalRiskResult(baseline, tuple(reasons))
    for token in tokens:
        if token in _COMMAND_SEPARATORS:
            if current:
                result = _most_restrictive(result, _evaluate_simple_command(current, line))
            if token == "|":
                result = _most_restrictive(
                    result,
                    TerminalRiskResult(TerminalRiskPolicy.ASK, ("pipe chain requires review",)),
                )
            current = []
            continue
        current.append(token)

    if current:
        result = _most_restrictive(result, _evaluate_simple_command(current, line))
    return result


def _space_shell_separators(line: str) -> str:
    # Keep this deliberately simple. It is not a shell parser; shlex handles
    # quoting after separators are isolated for command-boundary evaluation.
    return (
        line.replace("&&", " && ")
        .replace("||", " || ")
        .replace(";", " ; ")
        .replace("|", " | ")
    )


def _evaluate_simple_command(tokens: list[str], original_line: str) -> TerminalRiskResult:
    command = _unwrap_command(tokens)
    if not command:
        return TerminalRiskResult(TerminalRiskPolicy.SAFE)

    exe = command[0].split("/")[-1]
    joined = " ".join(command)

    if exe in _BLOCK_COMMANDS:
        return TerminalRiskResult(TerminalRiskPolicy.BLOCK, (f"blocked command: {exe}",))

    if exe == "rm" and any(arg.startswith("-") and "r" in arg and "f" in arg for arg in command[1:]):
        if _DANGEROUS_ROOT_PATTERN.search(joined):
            return TerminalRiskResult(TerminalRiskPolicy.BLOCK, ("recursive force removal targets root/home",))
        return TerminalRiskResult(TerminalRiskPolicy.ASK, ("recursive force removal",))

    if exe == "dd" and any(arg.startswith("of=/dev/") for arg in command[1:]):
        return TerminalRiskResult(TerminalRiskPolicy.BLOCK, ("raw device overwrite",))

    if exe in _WRITE_COMMANDS:
        if _SENSITIVE_TARGET_PATTERN.search(original_line):
            return TerminalRiskResult(TerminalRiskPolicy.ASK, ("write command targets sensitive path",))
        return TerminalRiskResult(TerminalRiskPolicy.ASK, (f"write-capable command: {exe}",))

    if exe == "git" and len(command) > 1 and command[1] in {"reset", "clean", "push"}:
        return TerminalRiskResult(TerminalRiskPolicy.ASK, (f"git {command[1]} requires review",))

    if exe in {"sed", "perl"} and any(arg.startswith("-i") for arg in command[1:]):
        return TerminalRiskResult(TerminalRiskPolicy.ASK, (f"in-place edit via {exe}",))

    if exe in _ALWAYS_ASK_COMMANDS and exe not in _READ_ONLY_COMMANDS:
        return TerminalRiskResult(TerminalRiskPolicy.ASK, (f"executor/network/package command: {exe}",))

    return TerminalRiskResult(TerminalRiskPolicy.SAFE)


def _unwrap_command(tokens: list[str]) -> list[str]:
    command = list(tokens)
    while command and command[0] in _WRAPPER_COMMANDS:
        wrapper = command.pop(0)
        if wrapper == "env":
            while command and "=" in command[0] and not command[0].startswith("="):
                command.pop(0)
        elif wrapper == "sudo":
            while command and command[0].startswith("-"):
                command.pop(0)
    return command


def _most_restrictive(left: TerminalRiskResult, right: TerminalRiskResult) -> TerminalRiskResult:
    policy = left.policy if _POLICY_RANK[left.policy] >= _POLICY_RANK[right.policy] else right.policy
    return TerminalRiskResult(policy, tuple(dict.fromkeys((*left.reasons, *right.reasons))))
