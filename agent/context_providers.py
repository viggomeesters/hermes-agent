"""Context provider registry primitives.

This module is a design/typing primitive for future context surfaces. It does
not integrate providers into prompt assembly yet; that would need explicit
cache-safety and UX decisions. The registry gives vault/repo/session/cron/MCP
context providers a shared shape without adding model tools to the core schema.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ContextProviderType(StrEnum):
    NORMAL = "normal"
    QUERY = "query"
    SUBMENU = "submenu"


class ContextSurface(StrEnum):
    CLI = "cli"
    GATEWAY = "gateway"
    TUI = "tui"
    ACP = "acp"
    CRON = "cron"


@dataclass(frozen=True)
class ContextProviderDescriptor:
    name: str
    display_name: str
    description: str
    provider_type: ContextProviderType = ContextProviderType.NORMAL
    surfaces: frozenset[ContextSurface] = field(default_factory=lambda: frozenset(ContextSurface))
    enabled_by_default: bool = True
    source: str = "builtin"

    def available_on(self, surface: ContextSurface) -> bool:
        return surface in self.surfaces


@dataclass(frozen=True)
class ContextItem:
    name: str
    content: str
    description: str = ""
    uri: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextQuery:
    query: str = ""
    extras: Mapping[str, Any] = field(default_factory=dict)
    surface: ContextSurface = ContextSurface.CLI


class ContextProvider(Protocol):
    descriptor: ContextProviderDescriptor

    def get_context_items(self, query: ContextQuery) -> Iterable[ContextItem]:
        ...


class FunctionContextProvider:
    """Small adapter for pure function providers used by tests/spikes."""

    def __init__(
        self,
        descriptor: ContextProviderDescriptor,
        func: Callable[[ContextQuery], Iterable[ContextItem]],
    ) -> None:
        self.descriptor = descriptor
        self._func = func

    def get_context_items(self, query: ContextQuery) -> Iterable[ContextItem]:
        return self._func(query)


class ContextProviderRegistry:
    """In-memory registry with deterministic ordering and surface filtering."""

    def __init__(self) -> None:
        self._providers: dict[str, ContextProvider] = {}

    def register(self, provider: ContextProvider) -> None:
        name = provider.descriptor.name.strip()
        if not name:
            raise ValueError("context provider name is required")
        if name in self._providers:
            raise ValueError(f"context provider already registered: {name}")
        self._providers[name] = provider

    def get(self, name: str) -> ContextProvider | None:
        return self._providers.get(name)

    def list_descriptors(self, *, surface: ContextSurface | None = None) -> list[ContextProviderDescriptor]:
        descriptors = [provider.descriptor for provider in self._providers.values()]
        if surface is not None:
            descriptors = [descriptor for descriptor in descriptors if descriptor.available_on(surface)]
        return sorted(descriptors, key=lambda descriptor: descriptor.name)

    def query(self, name: str, query: ContextQuery) -> list[ContextItem]:
        provider = self._providers.get(name)
        if provider is None:
            raise KeyError(f"unknown context provider: {name}")
        if not provider.descriptor.available_on(query.surface):
            raise ValueError(f"context provider '{name}' is not available on {query.surface}")
        return list(provider.get_context_items(query))


def default_context_provider_descriptors() -> list[ContextProviderDescriptor]:
    """Return the proposed built-in provider catalog without registering runtime hooks."""
    all_surfaces = frozenset(ContextSurface)
    interactive = frozenset({ContextSurface.CLI, ContextSurface.GATEWAY, ContextSurface.TUI, ContextSurface.ACP})
    return [
        ContextProviderDescriptor(
            name="repo",
            display_name="Repository",
            description="Workdir/git/diff/codebase context selected explicitly by the user or surface.",
            provider_type=ContextProviderType.SUBMENU,
            surfaces=interactive,
        ),
        ContextProviderDescriptor(
            name="vault",
            display_name="Vault",
            description="Bounded vault search/read context with source-backed excerpts and size limits.",
            provider_type=ContextProviderType.QUERY,
            surfaces=interactive,
        ),
        ContextProviderDescriptor(
            name="session",
            display_name="Session history",
            description="Past Hermes session snippets via session_search-like retrieval.",
            provider_type=ContextProviderType.QUERY,
            surfaces=interactive,
        ),
        ContextProviderDescriptor(
            name="cron",
            display_name="Cron jobs",
            description="Cron/job status and most recent output handles; no raw dump by default.",
            provider_type=ContextProviderType.SUBMENU,
            surfaces=frozenset({ContextSurface.CLI, ContextSurface.TUI, ContextSurface.GATEWAY}),
        ),
        ContextProviderDescriptor(
            name="mcp_resources",
            display_name="MCP resources",
            description="MCP resources/resourceTemplates exposed as context providers, not direct tool calls.",
            provider_type=ContextProviderType.SUBMENU,
            surfaces=all_surfaces,
            enabled_by_default=False,
            source="mcp",
        ),
    ]
