import pytest

from agent.context_providers import (
    ContextItem,
    ContextProviderDescriptor,
    ContextProviderRegistry,
    ContextProviderType,
    ContextQuery,
    ContextSurface,
    FunctionContextProvider,
    default_context_provider_descriptors,
)


def test_registry_lists_descriptors_deterministically_and_filters_by_surface():
    registry = ContextProviderRegistry()
    registry.register(FunctionContextProvider(
        ContextProviderDescriptor(
            name="vault",
            display_name="Vault",
            description="Vault search",
            provider_type=ContextProviderType.QUERY,
            surfaces=frozenset({ContextSurface.CLI}),
        ),
        lambda _query: [],
    ))
    registry.register(FunctionContextProvider(
        ContextProviderDescriptor(
            name="repo",
            display_name="Repository",
            description="Repo context",
            surfaces=frozenset({ContextSurface.CLI, ContextSurface.GATEWAY}),
        ),
        lambda _query: [],
    ))

    assert [d.name for d in registry.list_descriptors()] == ["repo", "vault"]
    assert [d.name for d in registry.list_descriptors(surface=ContextSurface.GATEWAY)] == ["repo"]


def test_registry_query_enforces_surface_availability():
    registry = ContextProviderRegistry()
    registry.register(FunctionContextProvider(
        ContextProviderDescriptor(
            name="session",
            display_name="Session",
            description="Session history",
            surfaces=frozenset({ContextSurface.CLI}),
        ),
        lambda query: [ContextItem(name="hit", content=query.query)],
    ))

    assert registry.query("session", ContextQuery(query="needle"))[0].content == "needle"
    with pytest.raises(ValueError, match="not available"):
        registry.query("session", ContextQuery(query="needle", surface=ContextSurface.GATEWAY))


def test_registry_rejects_duplicate_names():
    descriptor = ContextProviderDescriptor(
        name="repo",
        display_name="Repository",
        description="Repo context",
    )
    registry = ContextProviderRegistry()
    registry.register(FunctionContextProvider(descriptor, lambda _query: []))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(FunctionContextProvider(descriptor, lambda _query: []))


def test_default_descriptors_include_mcp_resources_as_disabled_context():
    descriptors = {descriptor.name: descriptor for descriptor in default_context_provider_descriptors()}

    assert {"repo", "vault", "session", "cron", "mcp_resources"}.issubset(descriptors)
    assert descriptors["mcp_resources"].provider_type is ContextProviderType.SUBMENU
    assert descriptors["mcp_resources"].enabled_by_default is False
    assert descriptors["mcp_resources"].source == "mcp"
