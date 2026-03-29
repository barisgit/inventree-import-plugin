"""Tests for the combined InvenTreeImportPlugin."""

from __future__ import annotations

from inventree_import_plugin.core import InvenTreeImportPlugin


def _settings(**overrides: object):
    defaults: dict[str, object] = {
        "LCSC_ENABLED": True,
        "LCSC_SUPPLIER": 101,
        "LCSC_DOWNLOAD_IMAGES": True,
        "MOUSER_ENABLED": True,
        "MOUSER_SUPPLIER": 202,
        "MOUSER_API_KEY": "test-key",
        "MOUSER_DOWNLOAD_IMAGES": True,
        "BULK_BATCH_SIZE": 50,
    }
    defaults.update(overrides)
    return defaults


class TestCombinedPluginSuppliers:
    def test_returns_both_configured_suppliers(self) -> None:
        plugin = InvenTreeImportPlugin()
        settings = _settings()
        plugin.get_setting = lambda key, default=None: settings.get(key, default)

        suppliers = plugin.get_suppliers()

        assert [supplier.slug for supplier in suppliers] == ["lcsc", "mouser"]

    def test_mouser_hidden_without_api_key(self) -> None:
        plugin = InvenTreeImportPlugin()
        settings = _settings(MOUSER_API_KEY="")
        plugin.get_setting = lambda key, default=None: settings.get(key, default)

        suppliers = plugin.get_suppliers()

        assert [supplier.slug for supplier in suppliers] == ["lcsc"]


class TestCombinedPluginUi:
    def test_part_panel_context(self) -> None:
        plugin = InvenTreeImportPlugin()
        plugin.plugin_static_file = lambda path: f"static/{path}"

        panels = plugin.get_ui_panels(None, {"target_model": "part"})

        assert len(panels) == 1
        assert panels[0]["key"] == "supplier-enrich"
        assert panels[0]["title"] == "Enrich Part"
        assert panels[0]["context"]["plugin_slug"] == plugin.SLUG
        assert panels[0]["source"] == "static/EnrichPanel.js:renderEnrichPanel"

    def test_partcategory_panel_context(self) -> None:
        plugin = InvenTreeImportPlugin()
        plugin.plugin_static_file = lambda path: f"static/{path}"

        panels = plugin.get_ui_panels(None, {"target_model": "partcategory"})

        assert len(panels) == 1
        assert panels[0]["key"] == "supplier-enrich"
        assert panels[0]["title"] == "Enrich Category Parts"
        assert panels[0]["context"]["plugin_slug"] == plugin.SLUG
        assert panels[0]["source"] == "static/EnrichPanel.js:renderEnrichPanel"

    def test_panel_returns_empty_for_unsupported_model(self) -> None:
        plugin = InvenTreeImportPlugin()
        plugin.plugin_static_file = lambda path: f"static/{path}"

        panels = plugin.get_ui_panels(None, {"target_model": "company"})

        assert panels == []

    def test_panel_returns_empty_for_none_context(self) -> None:
        plugin = InvenTreeImportPlugin()

        panels = plugin.get_ui_panels(None, None)

        assert panels == []

    def test_navigation_items_default_to_empty(self) -> None:
        plugin = InvenTreeImportPlugin()

        items = plugin.get_ui_navigation_items(None, {})

        assert items == []


class TestBulkPayloadParsing:
    class _Request:
        def __init__(self, data: dict[str, object]) -> None:
            self.data = data

    def test_deduplicates_and_normalizes_input(self) -> None:
        plugin = InvenTreeImportPlugin()
        settings = _settings(BULK_BATCH_SIZE=10)
        plugin.get_setting = lambda key, default=None: settings.get(key, default)

        part_ids, provider_slugs = plugin._parse_bulk_payload(
            self._Request(
                {
                    "part_ids": [5, "2", 5, 3],
                    "provider_slugs": ["mouser", "lcsc", "invalid"],
                }
            )
        )

        assert part_ids == [2, 3, 5]
        assert provider_slugs == ["mouser", "lcsc"]

    def test_requires_at_least_one_provider(self) -> None:
        plugin = InvenTreeImportPlugin()
        settings = _settings(BULK_BATCH_SIZE=10)
        plugin.get_setting = lambda key, default=None: settings.get(key, default)

        try:
            plugin._parse_bulk_payload(self._Request({"part_ids": [1], "provider_slugs": []}))
        except ValueError as exc:
            assert str(exc) == "At least one provider is required"
        else:
            raise AssertionError("Expected ValueError")
