"""Tests for the combined InvenTreeImportPlugin."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from inventree_import_plugin.models import PartData

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
    def test_part_panel_uses_hashed_asset_from_manifest(self) -> None:
        plugin = InvenTreeImportPlugin()
        plugin.plugin_static_file = lambda path: f"static/{path}"

        with patch.object(
            InvenTreeImportPlugin,
            "_resolve_enrich_panel_asset",
            return_value="EnrichPanelV2-abc123.js",
        ):
            panels = plugin.get_ui_panels(None, {"target_model": "part"})

        assert panels[0]["source"] == "static/EnrichPanelV2-abc123.js:renderEnrichPanel"

    def test_part_panel_falls_back_when_manifest_missing(self) -> None:
        plugin = InvenTreeImportPlugin()
        plugin.plugin_static_file = lambda path: f"static/{path}"

        with patch.object(
            InvenTreeImportPlugin,
            "_MANIFEST_PATH",
            Path("/nonexistent/.vite/manifest.json"),
        ):
            panels = plugin.get_ui_panels(None, {"target_model": "part"})

        assert panels[0]["source"] == "static/EnrichPanelV2.js:renderEnrichPanel"

    def test_partcategory_panel_context(self) -> None:
        plugin = InvenTreeImportPlugin()
        plugin.plugin_static_file = lambda path: f"static/{path}"

        with patch.object(
            InvenTreeImportPlugin,
            "_MANIFEST_PATH",
            Path("/nonexistent/.vite/manifest.json"),
        ):
            panels = plugin.get_ui_panels(None, {"target_model": "partcategory"})

        assert len(panels) == 1
        assert panels[0]["key"] == "supplier-enrich"
        assert panels[0]["title"] == "Enrich Category Parts"
        assert panels[0]["context"]["plugin_slug"] == plugin.SLUG

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


class TestResolveEnrichPanelAsset:
    def test_returns_hashed_filename_from_manifest(self) -> None:
        manifest = {"src/EnrichPanelV2.tsx": {"file": "EnrichPanelV2-abc123.js"}}
        mock_file = MagicMock()
        with (
            patch.object(InvenTreeImportPlugin, "_MANIFEST_PATH") as mock_path,
            patch("inventree_import_plugin.core.json.load", return_value=manifest),
        ):
            mock_path.open.return_value.__enter__ = MagicMock(return_value=mock_file)
            mock_path.open.return_value.__exit__ = MagicMock(return_value=False)
            result = InvenTreeImportPlugin._resolve_enrich_panel_asset()

        assert result == "EnrichPanelV2-abc123.js"

    def test_falls_back_when_manifest_file_missing(self) -> None:
        with patch.object(
            InvenTreeImportPlugin,
            "_MANIFEST_PATH",
            Path("/nonexistent/.vite/manifest.json"),
        ):
            result = InvenTreeImportPlugin._resolve_enrich_panel_asset()

        assert result == "EnrichPanelV2.js"

    def test_falls_back_when_entry_key_missing(self) -> None:
        manifest = {"src/Other.tsx": {"file": "Other.js"}}
        with (
            patch.object(InvenTreeImportPlugin, "_MANIFEST_PATH") as mock_path,
            patch("inventree_import_plugin.core.json.load", return_value=manifest),
        ):
            mock_path.open.return_value.__enter__ = MagicMock()
            mock_path.open.return_value.__exit__ = MagicMock(return_value=False)
            result = InvenTreeImportPlugin._resolve_enrich_panel_asset()

        assert result == "EnrichPanelV2.js"

    def test_falls_back_on_invalid_json(self) -> None:
        with (
            patch.object(InvenTreeImportPlugin, "_MANIFEST_PATH") as mock_path,
            patch(
                "inventree_import_plugin.core.json.load",
                side_effect=json.JSONDecodeError("", "", 0),
            ),
        ):
            mock_path.open.return_value.__enter__ = MagicMock()
            mock_path.open.return_value.__exit__ = MagicMock(return_value=False)
            result = InvenTreeImportPlugin._resolve_enrich_panel_asset()

        assert result == "EnrichPanelV2.js"


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


class TestCombinedPluginSupplierPartImport:
    def test_updates_existing_supplier_part_fields(self) -> None:
        plugin = InvenTreeImportPlugin()

        supplier_part = MagicMock()
        supplier_part.description = "Old desc"
        supplier_part.link = "https://old.example"
        supplier_part.available = 10

        data = PartData(
            sku="C123",
            name="Part",
            description="New desc",
            link="https://new.example",
            extra_data={"provider_slug": "lcsc", "stock": 25},
        )

        with (
            patch.object(plugin, "get_supplier_company_for", return_value="supplier-company"),
            patch("company.models.SupplierPart") as MockSupplierPart,
        ):
            MockSupplierPart.objects.get_or_create.return_value = (supplier_part, False)

            result = plugin.import_supplier_part(data, part="part", manufacturer_part="mfr")

        assert result is supplier_part
        assert supplier_part.description == "New desc"
        assert supplier_part.link == "https://new.example"
        supplier_part.save.assert_called_once()
        assert set(supplier_part.save.call_args.kwargs["update_fields"]) == {"description", "link"}
        supplier_part.update_available_quantity.assert_called_once_with(25)
