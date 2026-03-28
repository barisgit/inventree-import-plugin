"""Test configuration: stub out InvenTree internals that require a running server."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass


def _make_plugin_stubs() -> dict[str, types.ModuleType]:
    """Return minimal stubs for InvenTree plugin modules."""
    plugin_mod = types.ModuleType("plugin")
    mixins_mod = types.ModuleType("plugin.mixins")
    base_mod = types.ModuleType("plugin.base")
    base_supplier_mod = types.ModuleType("plugin.base.supplier")
    helpers_mod = types.ModuleType("plugin.base.supplier.helpers")

    class SettingsMixin:
        """Minimal stub — provides get_setting used by supplier plugins."""

        SETTINGS: dict = {}

        def get_setting(self, key: str, default: object = None) -> object:
            entry = self.SETTINGS.get(key, {})
            if isinstance(entry, dict):
                return entry.get("default", default)
            return default

    class SupplierMixin(SettingsMixin):
        """Minimal stub — satisfies SupplierMixin import in base.py."""

    class InvenTreePlugin(SettingsMixin):
        """Minimal stub — satisfies InvenTreePlugin import in base.py."""

    @dataclass
    class Supplier:
        slug: str
        name: str

    @dataclass
    class SearchResult:
        sku: str
        name: str
        exact: bool
        description: str | None = None
        price: str | None = None
        link: str | None = None
        image_url: str | None = None
        id: str | None = None

    mixins_mod.SettingsMixin = SettingsMixin  # type: ignore[attr-defined]
    mixins_mod.SupplierMixin = SupplierMixin  # type: ignore[attr-defined]
    plugin_mod.InvenTreePlugin = InvenTreePlugin  # type: ignore[attr-defined]
    plugin_mod.mixins = mixins_mod  # type: ignore[attr-defined]
    plugin_mod.base = base_mod  # type: ignore[attr-defined]
    base_mod.supplier = base_supplier_mod  # type: ignore[attr-defined]
    helpers_mod.Supplier = Supplier  # type: ignore[attr-defined]
    helpers_mod.SearchResult = SearchResult  # type: ignore[attr-defined]

    return {
        "plugin": plugin_mod,
        "plugin.mixins": mixins_mod,
        "plugin.base": base_mod,
        "plugin.base.supplier": base_supplier_mod,
        "plugin.base.supplier.helpers": helpers_mod,
    }


# Register the stubs before any project module is imported.
if "plugin" not in sys.modules:
    for _mod_name, _mod in _make_plugin_stubs().items():
        sys.modules[_mod_name] = _mod
