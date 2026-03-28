"""Test configuration: stub out InvenTree internals that require a running server."""

from __future__ import annotations

import sys
import types


def _make_plugin_stubs() -> tuple[types.ModuleType, types.ModuleType]:
    """Return minimal stubs for the ``plugin`` and ``plugin.mixins`` modules."""
    plugin_mod = types.ModuleType("plugin")
    mixins_mod = types.ModuleType("plugin.mixins")

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

    mixins_mod.SettingsMixin = SettingsMixin  # type: ignore[attr-defined]
    mixins_mod.SupplierMixin = SupplierMixin  # type: ignore[attr-defined]
    plugin_mod.InvenTreePlugin = InvenTreePlugin  # type: ignore[attr-defined]
    plugin_mod.mixins = mixins_mod  # type: ignore[attr-defined]

    return plugin_mod, mixins_mod


# Register the stubs before any project module is imported.
if "plugin" not in sys.modules:
    _plugin_mod, _mixins_mod = _make_plugin_stubs()
    sys.modules["plugin"] = _plugin_mod
    sys.modules["plugin.mixins"] = _mixins_mod
