from __future__ import annotations

from inventree_import_plugin.providers.aliexpress import AliExpressProvider
from inventree_import_plugin.providers.base import ProviderAdapter
from inventree_import_plugin.providers.lcsc import LCSCProvider
from inventree_import_plugin.providers.mouser import MouserProvider

_PROVIDER_ADAPTERS: tuple[ProviderAdapter, ...] = (
    LCSCProvider(),
    MouserProvider(),
    AliExpressProvider(),
)


def get_provider_adapters() -> tuple[ProviderAdapter, ...]:
    return _PROVIDER_ADAPTERS


def get_provider_adapter(provider_slug: str) -> ProviderAdapter:
    for adapter in _PROVIDER_ADAPTERS:
        if adapter.definition.slug == provider_slug:
            return adapter

    raise KeyError(f"Unknown provider: {provider_slug}")
