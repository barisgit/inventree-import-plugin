"""Tests for LCSCImportPlugin (lcsc_plugin.py)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from inventree_import_plugin.base import SearchResult
from inventree_import_plugin.lcsc_plugin import LCSCImportPlugin
from inventree_import_plugin.models import PartData, PriceBreak


@pytest.fixture()
def plugin() -> LCSCImportPlugin:
    return LCSCImportPlugin()


# ---------------------------------------------------------------------------
# get_suppliers
# ---------------------------------------------------------------------------


class TestGetSuppliers:
    def test_returns_lcsc_entry(self, plugin: LCSCImportPlugin) -> None:
        suppliers = plugin.get_suppliers()
        assert len(suppliers) == 1
        assert suppliers[0].name == "LCSC"

    def test_entry_has_slug(self, plugin: LCSCImportPlugin) -> None:
        assert plugin.get_suppliers()[0].slug == "lcsc"


# ---------------------------------------------------------------------------
# get_search_results
# ---------------------------------------------------------------------------


class TestGetSearchResults:
    _raw = [
        {
            "productCode": "C12345",
            "brandNameEn": "TI",
            "productModel": "LM358",
            "productIntroEn": "Dual op-amp",
        },
        {
            "productCode": "C99",
            "brandNameEn": "",
            "productModel": None,
            "productIntroEn": None,
        },
    ]

    def test_maps_fields_correctly(self, plugin: LCSCImportPlugin) -> None:
        with patch("inventree_import_plugin.lcsc_plugin.search_lcsc", return_value=self._raw):
            results = plugin.get_search_results("lcsc", "LM358")

        assert isinstance(results[0], SearchResult)
        assert results[0].sku == "C12345"
        assert results[0].name == "LM358"
        assert results[0].description == "Dual op-amp"
        assert results[0].exact is False

    def test_none_fields_coerced_to_empty_string(self, plugin: LCSCImportPlugin) -> None:
        with patch("inventree_import_plugin.lcsc_plugin.search_lcsc", return_value=self._raw):
            results = plugin.get_search_results("lcsc", "anything")

        assert results[1].name == ""
        assert results[1].description == ""

    def test_returns_all_results(self, plugin: LCSCImportPlugin) -> None:
        with patch("inventree_import_plugin.lcsc_plugin.search_lcsc", return_value=self._raw):
            results = plugin.get_search_results("lcsc", "x")
        assert len(results) == 2

    def test_empty_search_returns_empty_list(self, plugin: LCSCImportPlugin) -> None:
        with patch("inventree_import_plugin.lcsc_plugin.search_lcsc", return_value=[]):
            results = plugin.get_search_results("lcsc", "nomatch")
        assert results == []


# ---------------------------------------------------------------------------
# get_import_data
# ---------------------------------------------------------------------------


_SAMPLE_PART = PartData(
    sku="C12345",
    name="LM358",
    description="Dual op-amp",
    manufacturer_name="TI",
    manufacturer_part_number="LM358",
    image_url="https://example.com/img.jpg",
    price_breaks=[PriceBreak(quantity=1, price=0.15)],
)


class TestGetImportData:
    def test_returns_part_data(self, plugin: LCSCImportPlugin) -> None:
        with patch("inventree_import_plugin.lcsc_plugin.fetch_lcsc_part", return_value=_SAMPLE_PART):
            part = plugin.get_import_data("lcsc", "C12345")
        assert isinstance(part, PartData)
        assert part.sku == "C12345"

    def test_image_url_preserved_when_download_images_true(self, plugin: LCSCImportPlugin) -> None:
        with (
            patch("inventree_import_plugin.lcsc_plugin.fetch_lcsc_part", return_value=_SAMPLE_PART),
            patch.object(plugin, "get_setting", return_value=True),
        ):
            part = plugin.get_import_data("lcsc", "C12345")
        assert part.image_url == "https://example.com/img.jpg"

    def test_image_url_cleared_when_download_images_false(self, plugin: LCSCImportPlugin) -> None:
        with (
            patch("inventree_import_plugin.lcsc_plugin.fetch_lcsc_part", return_value=_SAMPLE_PART),
            patch.object(plugin, "get_setting", return_value=False),
        ):
            part = plugin.get_import_data("lcsc", "C12345")
        assert part.image_url == ""

    def test_passes_part_number_to_fetch(self, plugin: LCSCImportPlugin) -> None:
        with patch("inventree_import_plugin.lcsc_plugin.fetch_lcsc_part", return_value=_SAMPLE_PART) as mock:
            plugin.get_import_data("lcsc", "C99999")
        mock.assert_called_once_with("C99999")


# ---------------------------------------------------------------------------
# Plugin metadata
# ---------------------------------------------------------------------------


class TestPluginMetadata:
    def test_name(self) -> None:
        assert LCSCImportPlugin.NAME == "LCSCImportPlugin"

    def test_slug(self) -> None:
        assert LCSCImportPlugin.SLUG == "lcsc-import"

    def test_version(self) -> None:
        from inventree_import_plugin import PLUGIN_VERSION
        assert LCSCImportPlugin.VERSION == PLUGIN_VERSION

    def test_download_images_default_true(self) -> None:
        plugin = LCSCImportPlugin()
        assert plugin.get_setting("DOWNLOAD_IMAGES", True) is True
