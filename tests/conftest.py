"""Test configuration: stub out InvenTree internals that require a running server."""

from __future__ import annotations

import sys
import types


def _make_plugin_stub() -> types.ModuleType:
    """Return a minimal stub for the ``plugin`` module shipped with InvenTree."""
    mod = types.ModuleType("plugin")

    class InvenTreePlugin:
        """Minimal stub — only the interface used by BaseImportPlugin."""

        SETTINGS: dict = {}

        def get_setting(self, key: str, default: object = None) -> object:  # pragma: no cover
            entry = self.SETTINGS.get(key, {})
            if isinstance(entry, dict):
                return entry.get("default", default)
            return default

    mod.InvenTreePlugin = InvenTreePlugin  # type: ignore[attr-defined]
    return mod


# Register the stub before any project module is imported.
if "plugin" not in sys.modules:
    sys.modules["plugin"] = _make_plugin_stub()
