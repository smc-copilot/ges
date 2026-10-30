from __future__ import annotations

from ges.catalog.providers import Provider, load_providers


def package_incompatible(cap_id: str) -> tuple[str, ...]:
    providers = load_providers()
    provider: Provider | None = providers.get(cap_id)
    if provider is None:
        return ()
    return provider.incompatible
