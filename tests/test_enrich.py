"""Tests for BaseImportPlugin._enrich_part() and get_ui_panels()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from inventree_import_plugin.models import PartData, PartParameter, PriceBreak
from inventree_import_plugin.mouser_plugin import MouserImportPlugin
from inventree_import_plugin.lcsc_plugin import LCSCImportPlugin


@pytest.fixture()
def mouser_plugin() -> MouserImportPlugin:
    return MouserImportPlugin()


@pytest.fixture()
def lcsc_plugin() -> LCSCImportPlugin:
    return LCSCImportPlugin()


# ---------------------------------------------------------------------------
# get_ui_panels
# ---------------------------------------------------------------------------


class TestGetUiPanels:
    def test_mouser_returns_empty_for_non_part_model(self, mouser_plugin: MouserImportPlugin) -> None:
        result = mouser_plugin.get_ui_panels(None, {"target_model": "stockitem"})
        assert result == []

    def test_mouser_returns_panel_for_part_model(self, mouser_plugin: MouserImportPlugin) -> None:
        mouser_plugin.plugin_static_file = lambda f: f"static/{f}"  # type: ignore[method-assign]
        panels = mouser_plugin.get_ui_panels(None, {"target_model": "part"})
        assert len(panels) == 1
        assert panels[0]["key"] == "mouser-enrich"
        assert panels[0]["context"]["supplier_name"] == "Mouser"
        assert panels[0]["context"]["plugin_slug"] == "mouser-import"

    def test_lcsc_returns_empty_for_non_part_model(self, lcsc_plugin: LCSCImportPlugin) -> None:
        result = lcsc_plugin.get_ui_panels(None, {"target_model": "company"})
        assert result == []

    def test_lcsc_returns_panel_for_part_model(self, lcsc_plugin: LCSCImportPlugin) -> None:
        lcsc_plugin.plugin_static_file = lambda f: f"static/{f}"  # type: ignore[method-assign]
        panels = lcsc_plugin.get_ui_panels(None, {"target_model": "part"})
        assert len(panels) == 1
        assert panels[0]["key"] == "lcsc-enrich"
        assert panels[0]["context"]["supplier_name"] == "LCSC"
        assert panels[0]["context"]["plugin_slug"] == "lcsc-import"

    def test_none_context_returns_empty(self, mouser_plugin: MouserImportPlugin) -> None:
        result = mouser_plugin.get_ui_panels(None, None)
        assert result == []


# ---------------------------------------------------------------------------
# _enrich_part helpers
# ---------------------------------------------------------------------------


def _make_part(*, image: str = "", link: str = "") -> MagicMock:
    part = MagicMock()
    part.image = image
    part.link = link
    return part


def _make_supplier_part(sku: str = "C12345") -> MagicMock:
    sp = MagicMock()
    sp.SKU = sku
    return sp


_FRESH_DATA = PartData(
    sku="C12345",
    name="LM358",
    description="Dual op-amp",
    manufacturer_name="TI",
    manufacturer_part_number="LM358",
    image_url="https://example.com/img.jpg",
    datasheet_url="https://example.com/ds.pdf",
    price_breaks=[PriceBreak(quantity=1, price=0.15), PriceBreak(quantity=10, price=0.12)],
    parameters=[PartParameter(name="Voltage", value="5V", units="V")],
)

# Patch targets — imports happen inside _enrich_part() at call time.
_PT_PART = "part.models.Part"
_PT_SP = "company.models.SupplierPart"
_PT_PB = "company.models.SupplierPriceBreak"
_PT_TMPL = "part.models.PartParameterTemplate"
_PT_PARAM = "part.models.PartParameter"


def _stub_qs_for_sp(mock_sp_cls: MagicMock, sp_instance: MagicMock | None) -> None:
    """Wire MockSupplierPart.objects.filter().select_related().first() -> sp_instance."""
    qs = MagicMock()
    qs.select_related.return_value = qs
    qs.first.return_value = sp_instance
    mock_sp_cls.objects.filter.return_value = qs


def _stub_pb_qs(mock_pb_cls: MagicMock, existing: list[int]) -> None:
    """Wire MockSupplierPriceBreak.objects.filter().values_list() -> existing."""
    qs = MagicMock()
    qs.values_list.return_value = existing
    mock_pb_cls.objects.filter.return_value = qs


# ---------------------------------------------------------------------------
# _enrich_part tests
# ---------------------------------------------------------------------------


class TestEnrichPart:
    def _run(
        self,
        plugin: MouserImportPlugin,
        *,
        part: MagicMock | None = None,
        supplier_part: MagicMock | None = None,
        fresh_data: PartData | None = _FRESH_DATA,
        existing_pb_quantities: list[int] | None = None,
        param_exists: bool = False,
    ) -> dict:
        _part = part or _make_part()
        _sp = supplier_part or _make_supplier_part()

        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch(_PT_PB) as MockPB,
            patch(_PT_TMPL) as MockTmpl,
            patch(_PT_PARAM) as MockParam,
            patch.object(plugin, "get_import_data", return_value=fresh_data),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _part

            _stub_qs_for_sp(MockSP, _sp)
            _stub_pb_qs(MockPB, existing_pb_quantities or [])

            template_mock = MagicMock()
            MockTmpl.objects.get_or_create.return_value = (template_mock, True)
            MockParam.objects.filter.return_value.exists.return_value = param_exists

            return plugin._enrich_part(42)

    def test_part_not_found_returns_error(self, mouser_plugin: MouserImportPlugin) -> None:
        with patch(_PT_PART) as MockPart:
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.side_effect = Exception("not found")
            result = mouser_plugin._enrich_part(999)
        assert result["errors"]
        assert "999" in result["errors"][0]

    def test_no_supplier_part_returns_error(self, mouser_plugin: MouserImportPlugin) -> None:
        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _make_part()
            _stub_qs_for_sp(MockSP, None)
            result = mouser_plugin._enrich_part(1)
        assert result["errors"]

    def test_image_updated_when_part_has_no_image(self, mouser_plugin: MouserImportPlugin) -> None:
        part = _make_part(image="")
        result = self._run(mouser_plugin, part=part)
        assert "image" in result["updated"]
        part.set_image_from_url.assert_called_once_with(_FRESH_DATA.image_url)

    def test_image_skipped_when_part_already_has_image(self, mouser_plugin: MouserImportPlugin) -> None:
        part = _make_part(image="existing.jpg")
        result = self._run(mouser_plugin, part=part)
        assert "image" in result["skipped"]
        part.set_image_from_url.assert_not_called()

    def test_datasheet_link_updated_when_empty(self, mouser_plugin: MouserImportPlugin) -> None:
        part = _make_part(link="")
        result = self._run(mouser_plugin, part=part)
        assert "datasheet_link" in result["updated"]
        assert part.link == _FRESH_DATA.datasheet_url

    def test_datasheet_link_skipped_when_already_set(self, mouser_plugin: MouserImportPlugin) -> None:
        part = _make_part(link="https://existing.com/ds.pdf")
        result = self._run(mouser_plugin, part=part)
        assert "datasheet_link" in result["skipped"]

    def test_price_breaks_added_for_new_quantities(self, mouser_plugin: MouserImportPlugin) -> None:
        result = self._run(mouser_plugin, existing_pb_quantities=[])
        assert "price_break:1" in result["updated"]
        assert "price_break:10" in result["updated"]

    def test_price_breaks_skipped_for_existing_quantities(self, mouser_plugin: MouserImportPlugin) -> None:
        result = self._run(mouser_plugin, existing_pb_quantities=[1, 10])
        assert "price_break:1" in result["skipped"]
        assert "price_break:10" in result["skipped"]

    def test_parameter_added_when_not_present(self, mouser_plugin: MouserImportPlugin) -> None:
        result = self._run(mouser_plugin, param_exists=False)
        assert "parameter:Voltage" in result["updated"]

    def test_parameter_skipped_when_already_present(self, mouser_plugin: MouserImportPlugin) -> None:
        result = self._run(mouser_plugin, param_exists=True)
        assert "parameter:Voltage" in result["skipped"]

    def test_fetch_exception_returns_error(self, mouser_plugin: MouserImportPlugin) -> None:
        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch.object(mouser_plugin, "get_import_data", side_effect=RuntimeError("network error")),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _make_part()
            _stub_qs_for_sp(MockSP, _make_supplier_part())
            result = mouser_plugin._enrich_part(1)
        assert result["errors"]
        assert "network error" in result["errors"][0]

    def test_none_fresh_data_returns_error(self, mouser_plugin: MouserImportPlugin) -> None:
        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch.object(mouser_plugin, "get_import_data", return_value=None),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _make_part()
            _stub_qs_for_sp(MockSP, _make_supplier_part())
            result = mouser_plugin._enrich_part(1)
        assert result["errors"]

    def test_result_has_expected_keys(self, mouser_plugin: MouserImportPlugin) -> None:
        result = self._run(mouser_plugin)
        assert set(result.keys()) == {"updated", "skipped", "errors"}

    def test_lcsc_plugin_enrich_returns_structured_result(self, lcsc_plugin: LCSCImportPlugin) -> None:
        """LCSC plugin inherits the same enrich logic from BaseImportPlugin."""
        result = self._run(lcsc_plugin)
        assert set(result.keys()) == {"updated", "skipped", "errors"}
