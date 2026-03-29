"""Tests for BaseImportPlugin._enrich_part(), setup_urls(), and get_ui_panels()."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from inventree_import_plugin.lcsc_plugin import LCSCImportPlugin
from inventree_import_plugin.models import PartData, PartParameter, PriceBreak
from inventree_import_plugin.mouser_plugin import MouserImportPlugin


@pytest.fixture(autouse=True)
def _mock_django():
    """Provide minimal Django/DRF stubs when the real packages are absent."""
    if "django" in sys.modules:
        return
    django = types.ModuleType("django")
    django.urls = types.ModuleType("django.urls")  # type: ignore[attr-defined]

    class _FakeUrlPattern:
        def __init__(self, pattern, callback, name):
            self.pattern = pattern
            self.callback = callback
            self.name = name

    def _path(route, view, *, name=None):
        return _FakeUrlPattern(route, view, name)

    django.urls.path = _path  # type: ignore[attr-defined]

    rest_framework = types.ModuleType("rest_framework")
    rf_views = types.ModuleType("rest_framework.views")

    def _as_view(cls):
        def _view(request, **kwargs):
            return None

        _view.view_class = cls  # type: ignore[attr-defined]
        return _view

    rf_views.APIView = type(  # type: ignore[attr-defined]
        "APIView",
        (),
        {"as_view": classmethod(_as_view)},
    )
    rest_framework.views = rf_views  # type: ignore[attr-defined]
    rf_response = types.ModuleType("rest_framework.response")
    rf_response.Response = type("Response", (), {})  # type: ignore[attr-defined]
    rest_framework.response = rf_response  # type: ignore[attr-defined]

    inventree = types.ModuleType("InvenTree")
    inventree_permissions = types.ModuleType("InvenTree.permissions")
    inventree_permissions.RolePermission = type("RolePermission", (), {})  # type: ignore[attr-defined]
    inventree.permissions = inventree_permissions  # type: ignore[attr-defined]

    sys.modules["django"] = django
    sys.modules["django.urls"] = django.urls  # type: ignore[attr-defined]
    sys.modules["InvenTree"] = inventree
    sys.modules["InvenTree.permissions"] = inventree_permissions
    sys.modules["rest_framework"] = rest_framework
    sys.modules["rest_framework.views"] = rest_framework.views  # type: ignore[attr-defined]
    sys.modules["rest_framework.response"] = rest_framework.response  # type: ignore[attr-defined]


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
    """Legacy plugins no longer register UI panels (handled by InvenTreeImportPlugin)."""

    def test_mouser_returns_empty_for_part_model(self, mouser_plugin: MouserImportPlugin) -> None:
        result = mouser_plugin.get_ui_panels(None, {"target_model": "part"})
        assert result == []

    def test_mouser_returns_empty_for_non_part_model(
        self, mouser_plugin: MouserImportPlugin
    ) -> None:
        result = mouser_plugin.get_ui_panels(None, {"target_model": "stockitem"})
        assert result == []

    def test_mouser_returns_empty_for_none_context(self, mouser_plugin: MouserImportPlugin) -> None:
        result = mouser_plugin.get_ui_panels(None, None)
        assert result == []

    def test_lcsc_returns_empty_for_part_model(self, lcsc_plugin: LCSCImportPlugin) -> None:
        result = lcsc_plugin.get_ui_panels(None, {"target_model": "part"})
        assert result == []

    def test_lcsc_returns_empty_for_non_part_model(self, lcsc_plugin: LCSCImportPlugin) -> None:
        result = lcsc_plugin.get_ui_panels(None, {"target_model": "company"})
        assert result == []


# ---------------------------------------------------------------------------
# setup_urls
# ---------------------------------------------------------------------------


class TestSetupUrls:
    def test_setup_urls_returns_urls_list(self, mouser_plugin: MouserImportPlugin) -> None:
        urls = mouser_plugin.setup_urls()
        assert len(urls) == 1
        assert urls[0].name == "enrich"

    def test_setup_urls_idempotent(self, mouser_plugin: MouserImportPlugin) -> None:
        first_urls = mouser_plugin.setup_urls()
        second_urls = mouser_plugin.setup_urls()
        assert len(first_urls) == len(second_urls)

    def test_setup_urls_pattern_contains_enrich(self, mouser_plugin: MouserImportPlugin) -> None:
        pattern = mouser_plugin.setup_urls()[0]
        route = str(pattern.pattern)
        assert "enrich" in route
        assert "part_id" in route

    def test_lcsc_setup_urls(self, lcsc_plugin: LCSCImportPlugin) -> None:
        urls = lcsc_plugin.setup_urls()
        assert len(urls) == 1
        assert urls[0].name == "enrich"

    def test_setup_urls_uses_part_change_role(self, mouser_plugin: MouserImportPlugin) -> None:
        view = mouser_plugin.setup_urls()[0]
        callback = getattr(view, "callback", None)
        view_class = getattr(callback, "view_class", None)

        assert view_class is not None
        assert getattr(view_class, "role_required", None) == "part.change"


# ---------------------------------------------------------------------------
# _enrich_part helpers
# ---------------------------------------------------------------------------


def _make_part(*, image: str = "", link: str = "", description: str = "") -> MagicMock:
    part = MagicMock()
    part.image = image
    part.link = link
    part.description = description
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
    link="https://example.com/part/C12345",
    image_url="https://example.com/img.jpg",
    datasheet_url="https://example.com/ds.pdf",
    price_breaks=[PriceBreak(quantity=1, price=0.15), PriceBreak(quantity=10, price=0.12)],
    parameters=[PartParameter(name="Voltage", value="5V", units="V")],
)

# Patch targets — imports happen inside _enrich_part() at call time.
_PT_PART = "part.models.Part"
_PT_SP = "company.models.SupplierPart"
_PT_PB = "company.models.SupplierPriceBreak"
_PT_CT = "django.contrib.contenttypes.models.ContentType"
_PT_TMPL = "common.models.ParameterTemplate"
_PT_PARAM = "common.models.Parameter"
_PT_ATTACH = "common.models.Attachment"


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
    _DL_PATCH = "inventree_import_plugin.base._download_and_set_image"

    def _run(
        self,
        plugin: MouserImportPlugin,
        *,
        part: MagicMock | None = None,
        supplier_part: MagicMock | None = None,
        fresh_data: PartData | None = _FRESH_DATA,
        existing_pb_quantities: list[int] | None = None,
        param_exists: bool = False,
        dry_run: bool = False,
        has_datasheet_attachment: bool = False,
    ) -> dict:
        _part = part or _make_part()
        _sp = supplier_part or _make_supplier_part()

        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch(_PT_PB) as MockPB,
            patch(_PT_CT) as MockContentType,
            patch(_PT_TMPL) as MockTmpl,
            patch(_PT_PARAM) as MockParam,
            patch(_PT_ATTACH) as MockAttach,
            patch(self._DL_PATCH) as _mock_dl,
            patch.object(plugin, "get_import_data", return_value=fresh_data),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _part
            MockContentType.objects.get_for_model.return_value = "part-content-type"

            _stub_qs_for_sp(MockSP, _sp)
            _stub_pb_qs(MockPB, existing_pb_quantities or [])

            template_mock = MagicMock()
            MockTmpl.objects.get_or_create.return_value = (template_mock, True)
            MockParam.objects.filter.return_value.exists.return_value = param_exists

            _stub_attachment_for_base(MockAttach, has_datasheet=has_datasheet_attachment)

            return plugin._enrich_part(42, dry_run=dry_run)

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
        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch(_PT_PB) as MockPB,
            patch(_PT_CT) as MockContentType,
            patch(_PT_TMPL) as MockTmpl,
            patch(_PT_PARAM) as MockParam,
            patch(_PT_ATTACH) as MockAttach,
            patch(self._DL_PATCH) as mock_dl,
            patch.object(mouser_plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = part
            MockContentType.objects.get_for_model.return_value = "ct"
            _stub_qs_for_sp(MockSP, _make_supplier_part())
            _stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment_for_base(MockAttach, has_datasheet=False)

            result = mouser_plugin._enrich_part(42)

        assert "image" in result["updated"]
        mock_dl.assert_called_once_with(part, _FRESH_DATA.image_url)

    def test_image_skipped_when_part_already_has_image(
        self, mouser_plugin: MouserImportPlugin
    ) -> None:
        part = _make_part(image="existing.jpg")
        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch(_PT_PB) as MockPB,
            patch(_PT_CT) as MockContentType,
            patch(_PT_TMPL) as MockTmpl,
            patch(_PT_PARAM) as MockParam,
            patch(_PT_ATTACH) as MockAttach,
            patch(self._DL_PATCH) as mock_dl,
            patch.object(mouser_plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = part
            MockContentType.objects.get_for_model.return_value = "ct"
            _stub_qs_for_sp(MockSP, _make_supplier_part())
            _stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment_for_base(MockAttach, has_datasheet=False)

            result = mouser_plugin._enrich_part(42)

        assert "image" in result["skipped"]
        mock_dl.assert_not_called()

    def test_datasheet_link_updated_when_empty(self, mouser_plugin: MouserImportPlugin) -> None:
        result = self._run(mouser_plugin, has_datasheet_attachment=False)
        assert "datasheet_link" in result["updated"]

    def test_datasheet_link_skipped_when_already_set(
        self, mouser_plugin: MouserImportPlugin
    ) -> None:
        result = self._run(mouser_plugin, has_datasheet_attachment=True)
        assert "datasheet_link" in result["skipped"]

    def test_price_breaks_added_for_new_quantities(self, mouser_plugin: MouserImportPlugin) -> None:
        result = self._run(mouser_plugin, existing_pb_quantities=[])
        assert "price_break:1" in result["updated"]
        assert "price_break:10" in result["updated"]

    def test_price_breaks_skipped_for_existing_quantities(
        self, mouser_plugin: MouserImportPlugin
    ) -> None:
        result = self._run(mouser_plugin, existing_pb_quantities=[1, 10])
        assert "price_break:1" in result["skipped"]
        assert "price_break:10" in result["skipped"]

    def test_parameter_added_when_not_present(self, mouser_plugin: MouserImportPlugin) -> None:
        result = self._run(mouser_plugin, param_exists=False)
        assert "parameter:Voltage" in result["updated"]

    def test_parameter_skipped_when_already_present(
        self, mouser_plugin: MouserImportPlugin
    ) -> None:
        result = self._run(mouser_plugin, param_exists=True)
        assert "parameter:Voltage" in result["skipped"]

    def test_fetch_exception_returns_error(self, mouser_plugin: MouserImportPlugin) -> None:
        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch.object(
                mouser_plugin, "get_import_data", side_effect=RuntimeError("network error")
            ),
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

    def test_lcsc_plugin_enrich_returns_structured_result(
        self, lcsc_plugin: LCSCImportPlugin
    ) -> None:
        """LCSC plugin inherits the same enrich logic from BaseImportPlugin."""
        result = self._run(lcsc_plugin)
        assert set(result.keys()) == {"updated", "skipped", "errors"}


# ---------------------------------------------------------------------------
# SupplierPart field enrichment in base._enrich_part
# ---------------------------------------------------------------------------


class TestEnrichSupplierPartFields:
    """SupplierPart description/link/available are updated when values change."""

    _DL_PATCH = "inventree_import_plugin.base._download_and_set_image"

    def _run(self, plugin, *, supplier_part=None, fresh_data=None, dry_run=False):
        helper = TestEnrichPart()
        return helper._run(
            plugin,
            supplier_part=supplier_part,
            fresh_data=fresh_data or _FRESH_DATA,
            dry_run=dry_run,
        )

    def test_supplier_part_description_updated(self, mouser_plugin: MouserImportPlugin) -> None:
        sp = _make_supplier_part()
        sp.description = ""
        sp.link = "https://already-set.com"
        result = self._run(mouser_plugin, supplier_part=sp)
        assert "supplier_part:description" in result["updated"]
        assert sp.description == _FRESH_DATA.description

    def test_supplier_part_description_updated_when_changed(
        self, mouser_plugin: MouserImportPlugin
    ) -> None:
        sp = _make_supplier_part()
        sp.description = "Old description"
        sp.link = _FRESH_DATA.link
        result = self._run(mouser_plugin, supplier_part=sp)
        assert "supplier_part:description" in result["updated"]
        assert sp.description == _FRESH_DATA.description
        sp.save.assert_called_once()

    def test_supplier_part_link_updated(self, mouser_plugin: MouserImportPlugin) -> None:
        sp = _make_supplier_part()
        sp.description = "Already set"
        sp.link = ""
        result = self._run(mouser_plugin, supplier_part=sp)
        assert "supplier_part:link" in result["updated"]
        assert sp.link == _FRESH_DATA.link

    def test_supplier_part_link_updated_when_changed(
        self, mouser_plugin: MouserImportPlugin
    ) -> None:
        sp = _make_supplier_part()
        sp.description = _FRESH_DATA.description
        sp.link = "https://old-link.com"
        result = self._run(mouser_plugin, supplier_part=sp)
        assert "supplier_part:link" in result["updated"]
        assert sp.link == _FRESH_DATA.link
        sp.save.assert_called_once()

    def test_supplier_part_available_updated_from_stock(
        self, mouser_plugin: MouserImportPlugin
    ) -> None:
        data_with_stock = PartData(
            sku="C12345",
            name="LM358",
            description="Dual op-amp",
            link="https://example.com",
            extra_data={"stock": 250},
        )
        sp = _make_supplier_part()
        sp.description = "Already set"
        sp.link = "https://already.set"
        sp.available = 0
        result = self._run(mouser_plugin, supplier_part=sp, fresh_data=data_with_stock)
        assert "supplier_part:available" in result["updated"]
        sp.update_available_quantity.assert_called_once_with(250)

    def test_supplier_part_available_updated_when_changed(
        self, mouser_plugin: MouserImportPlugin
    ) -> None:
        data_with_stock = PartData(
            sku="C12345",
            name="LM358",
            description="Dual op-amp",
            link="https://example.com",
            extra_data={"stock": 500},
        )
        sp = _make_supplier_part()
        sp.description = _FRESH_DATA.description
        sp.link = _FRESH_DATA.link
        sp.available = 250
        result = self._run(mouser_plugin, supplier_part=sp, fresh_data=data_with_stock)
        assert "supplier_part:available" in result["updated"]
        sp.update_available_quantity.assert_called_once_with(500)

    def test_supplier_part_skipped_when_values_match(
        self, mouser_plugin: MouserImportPlugin
    ) -> None:
        sp = _make_supplier_part()
        sp.description = _FRESH_DATA.description
        sp.link = _FRESH_DATA.link
        result = self._run(mouser_plugin, supplier_part=sp)
        assert "supplier_part:description" not in result["updated"]
        assert "supplier_part:link" not in result["updated"]

    def test_supplier_part_not_saved_when_no_changes(
        self, mouser_plugin: MouserImportPlugin
    ) -> None:
        sp = _make_supplier_part()
        sp.description = _FRESH_DATA.description
        sp.link = _FRESH_DATA.link
        result = self._run(mouser_plugin, supplier_part=sp)
        sp.save.assert_not_called()

    def test_preview_reports_supplier_part_without_saving(
        self, mouser_plugin: MouserImportPlugin
    ) -> None:
        sp = _make_supplier_part()
        sp.description = ""
        sp.link = ""
        result = self._run(mouser_plugin, supplier_part=sp, dry_run=True)
        assert "supplier_part:description" in result["updated"]
        assert "supplier_part:link" in result["updated"]
        sp.save.assert_not_called()


# ---------------------------------------------------------------------------
# dry_run (GET preview) tests
# ---------------------------------------------------------------------------


class TestEnrichPreview:
    """Verify dry_run=True returns preview without persisting."""

    _DL_PATCH = "inventree_import_plugin.base._download_and_set_image"

    def _run_preview(self, plugin, **kwargs):
        kwargs.setdefault("dry_run", True)
        # Reuse TestEnrichPart._run with dry_run
        helper = TestEnrichPart()
        return helper._run(plugin, **kwargs)

    def test_preview_returns_same_keys(self, mouser_plugin: MouserImportPlugin) -> None:
        result = self._run_preview(mouser_plugin)
        assert set(result.keys()) == {"updated", "skipped", "errors"}

    def test_preview_does_not_download_image(self, mouser_plugin: MouserImportPlugin) -> None:
        part = _make_part(image="")
        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch(_PT_PB) as MockPB,
            patch(_PT_CT) as MockContentType,
            patch(_PT_TMPL) as MockTmpl,
            patch(_PT_PARAM) as MockParam,
            patch(_PT_ATTACH) as MockAttach,
            patch(self._DL_PATCH) as mock_dl,
            patch.object(mouser_plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = part
            MockContentType.objects.get_for_model.return_value = "ct"
            _stub_qs_for_sp(MockSP, _make_supplier_part())
            _stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment_for_base(MockAttach, has_datasheet=False)

            result = mouser_plugin._enrich_part(42, dry_run=True)

        assert "image" in result["updated"]
        # Image download must NOT have been called in dry_run mode
        mock_dl.assert_not_called()

    def test_preview_does_not_save_datasheet(self, mouser_plugin: MouserImportPlugin) -> None:
        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch(_PT_PB) as MockPB,
            patch(_PT_CT) as MockContentType,
            patch(_PT_TMPL) as MockTmpl,
            patch(_PT_PARAM) as MockParam,
            patch(_PT_ATTACH) as MockAttach,
            patch(self._DL_PATCH),
            patch.object(mouser_plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _make_part()
            MockContentType.objects.get_for_model.return_value = "ct"
            _stub_qs_for_sp(MockSP, _make_supplier_part())
            _stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment_for_base(MockAttach, has_datasheet=False)

            result = mouser_plugin._enrich_part(42, dry_run=True)

        assert "datasheet_link" in result["updated"]
        # Attachment must NOT have been created in dry_run
        MockAttach.objects.create.assert_not_called()

    def test_preview_does_not_create_price_breaks(self, mouser_plugin: MouserImportPlugin) -> None:
        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch(_PT_PB) as MockPB,
            patch(_PT_CT) as MockContentType,
            patch(_PT_TMPL) as MockTmpl,
            patch(_PT_PARAM) as MockParam,
            patch(_PT_ATTACH) as MockAttach,
            patch(self._DL_PATCH),
            patch.object(mouser_plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _make_part()
            MockContentType.objects.get_for_model.return_value = "ct"
            _stub_qs_for_sp(MockSP, _make_supplier_part())
            _stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment_for_base(MockAttach, has_datasheet=False)

            result = mouser_plugin._enrich_part(42, dry_run=True)

        assert "price_break:1" in result["updated"]
        assert "price_break:10" in result["updated"]
        MockPB.objects.create.assert_not_called()

    def test_preview_does_not_create_parameters(self, mouser_plugin: MouserImportPlugin) -> None:
        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch(_PT_PB) as MockPB,
            patch(_PT_CT) as MockContentType,
            patch(_PT_TMPL) as MockTmpl,
            patch(_PT_PARAM) as MockParam,
            patch(_PT_ATTACH) as MockAttach,
            patch(self._DL_PATCH),
            patch.object(mouser_plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _make_part()
            MockContentType.objects.get_for_model.return_value = "ct"
            _stub_qs_for_sp(MockSP, _make_supplier_part())
            _stub_pb_qs(MockPB, [1, 10])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment_for_base(MockAttach, has_datasheet=False)

            result = mouser_plugin._enrich_part(42, dry_run=True)

        assert "parameter:Voltage" in result["updated"]
        MockParam.objects.create.assert_not_called()
        MockTmpl.objects.get_or_create.assert_not_called()


# ---------------------------------------------------------------------------
# _download_and_set_image fallback chain
# ---------------------------------------------------------------------------


class TestDownloadAndSetImage:
    _FUNC = "inventree_import_plugin.base._download_and_set_image"

    def test_uses_inventree_helper_when_available(self) -> None:
        part = MagicMock()
        img = MagicMock()
        img.format = "PNG"
        img.save.side_effect = lambda buffer, format: buffer.write(b"image-bytes")

        helper_mod = types.ModuleType("InvenTree.helpers_model")
        helper_mod.download_image_from_url = MagicMock(return_value=img)  # type: ignore[attr-defined]
        inventree_mod = sys.modules.get("InvenTree", types.ModuleType("InvenTree"))

        # Stub django.core.files.base.ContentFile so the first code path works
        django_files_base = types.ModuleType("django.core.files.base")

        class _FakeContentFile:
            def __init__(self, data):
                self.data = data

        django_files_base.ContentFile = _FakeContentFile  # type: ignore[attr-defined]
        sys.modules["django.core.files.base"] = django_files_base

        try:
            with patch.dict(
                sys.modules,
                {"InvenTree": inventree_mod, "InvenTree.helpers_model": helper_mod},
            ):
                from inventree_import_plugin.base import _download_and_set_image as fn

                fn(part, "https://example.com/test.jpg")

            part.image.save.assert_called_once()
            args, kwargs = part.image.save.call_args
            assert args[0].startswith("part_")
            assert args[0].endswith(".png")
            assert kwargs == {"save": True}
            helper_mod.download_image_from_url.assert_called_once_with(
                "https://example.com/test.jpg"
            )
        finally:
            sys.modules.pop("django.core.files.base", None)

    def test_falls_back_to_set_image_from_url(self) -> None:
        part = MagicMock()
        part.set_image_from_url = MagicMock()

        sys.modules.pop("InvenTree.helpers_model", None)
        from inventree_import_plugin.base import _download_and_set_image as fn

        fn(part, "https://example.com/test.jpg")

        part.set_image_from_url.assert_called_once_with("https://example.com/test.jpg")


# ---------------------------------------------------------------------------
# enrich_part_for_provider (services/enrich.py) structured diff tests
# ---------------------------------------------------------------------------

# Patch targets for the services-level function.
_SVC_PART = "part.models.Part"
_SVC_SP = "company.models.SupplierPart"
_SVC_PB = "company.models.SupplierPriceBreak"
_SVC_CT = "django.contrib.contenttypes.models.ContentType"
_SVC_TMPL = "common.models.ParameterTemplate"
_SVC_PARAM = "common.models.Parameter"
_SVC_DL = "inventree_import_plugin.services.enrich._download_and_set_image"
_SVC_ATTACH = "common.models.Attachment"


class _MockProviderAdapter:
    """Minimal adapter stub for _provider_result."""

    class _Definition:
        name = "TestProvider"
        slug = "test-provider"

    definition = _Definition()


class _MockCorePlugin:
    """Minimal plugin mock that has _provider_result and provider methods."""

    def _provider_result(self, provider_slug, part_id, updated, skipped, errors, *, diff=None):
        return {
            "provider_slug": provider_slug,
            "provider_name": "TestProvider",
            "part_id": part_id,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            **({"diff": diff} if diff is not None else {}),
        }

    def get_supplier_company_for(self, provider_slug):
        return MagicMock()

    def get_import_data(self, provider_slug, sku):
        return _FRESH_DATA


def _svc_stub_qs_for_sp(mock_sp_cls, sp_instance):
    qs = MagicMock()
    qs.select_related.return_value = qs
    qs.first.return_value = sp_instance
    mock_sp_cls.objects.filter.return_value = qs


def _svc_stub_pb_qs(mock_pb_cls, existing):
    qs = MagicMock()
    qs.values_list.return_value = existing
    mock_pb_cls.objects.filter.return_value = qs


def _stub_attachment(mock_attach_cls, *, has_datasheet=False, existing_link=None):
    """Wire Attachment.objects.filter(...).exists() and .first() for datasheet checks."""
    qs = MagicMock()
    qs.exists.return_value = has_datasheet
    if has_datasheet or existing_link:
        att_mock = MagicMock(link=existing_link or "https://existing.com/ds.pdf")
        qs.first.return_value = att_mock
    else:
        qs.first.return_value = None
    mock_attach_cls.objects.filter.return_value = qs


def _stub_attachment_for_base(mock_attach_cls, *, has_datasheet=False):
    """Wire Attachment mock for base.py _enrich_part (uses filter + create pattern)."""
    qs = MagicMock()
    qs.exists.return_value = has_datasheet
    mock_attach_cls.objects.filter.return_value = qs


class TestEnrichPartForProviderDiff:
    """Test enrich_part_for_provider returns structured diff in preview mode."""

    def _run(
        self,
        *,
        dry_run=True,
        existing_pb_quantities=None,
        param_exists=False,
        part=None,
        supplier_part=None,
        has_datasheet_attachment=False,
    ):
        from inventree_import_plugin.services.enrich import enrich_part_for_provider

        plugin = _MockCorePlugin()
        _part = part or _make_part()
        _sp = supplier_part or _make_supplier_part()

        with (
            patch(_SVC_PART) as MockPart,
            patch(_SVC_SP) as MockSP,
            patch(_SVC_PB) as MockPB,
            patch(_SVC_CT) as MockContentType,
            patch(_SVC_TMPL) as MockTmpl,
            patch(_SVC_PARAM) as MockParam,
            patch(_SVC_DL),
            patch(_SVC_ATTACH) as MockAttach,
            patch.object(plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _part
            MockContentType.objects.get_for_model.return_value = "part-content-type"
            _svc_stub_qs_for_sp(MockSP, _sp)
            _svc_stub_pb_qs(MockPB, existing_pb_quantities or [])

            template_mock = MagicMock()
            MockTmpl.objects.get_or_create.return_value = (template_mock, True)
            MockParam.objects.filter.return_value.exists.return_value = param_exists
            existing_param = MagicMock(data="5V") if param_exists else None
            MockParam.objects.filter.return_value.first.return_value = existing_param

            _stub_attachment(MockAttach, has_datasheet=has_datasheet_attachment)

            return enrich_part_for_provider(plugin, "test-provider", 42, dry_run=dry_run)

    def test_preview_includes_diff_key(self):
        result = self._run(dry_run=True)
        assert "diff" in result
        assert "updated" in result
        assert "skipped" in result
        assert "errors" in result

    def test_apply_does_not_include_diff(self):
        result = self._run(dry_run=False)
        assert "diff" not in result

    def test_diff_has_expected_top_level_keys(self):
        result = self._run(dry_run=True)
        diff = result["diff"]
        assert set(diff.keys()) == {
            "image",
            "datasheet",
            "price_breaks",
            "parameters",
            "part_fields",
            "supplier_part",
        }

    def test_diff_image_when_part_has_no_image(self):
        result = self._run(dry_run=True, part=_make_part(image=""))
        image_diff = result["diff"]["image"]
        assert image_diff["field"] == "image"
        assert image_diff["current"] is None
        assert image_diff["incoming"] == _FRESH_DATA.image_url
        assert image_diff["status"] == "new"

    def test_diff_image_when_part_already_has_image(self):
        result = self._run(dry_run=True, part=_make_part(image="existing.jpg"))
        image_diff = result["diff"]["image"]
        assert image_diff["current"] == "existing.jpg"
        assert image_diff["status"] == "skipped"

    def test_diff_datasheet_when_no_existing_attachment(self):
        result = self._run(dry_run=True, has_datasheet_attachment=False)
        ds_diff = result["diff"]["datasheet"]
        assert ds_diff["field"] == "datasheet_link"
        assert ds_diff["current"] is None
        assert ds_diff["incoming"] == _FRESH_DATA.datasheet_url
        assert ds_diff["status"] == "new"

    def test_diff_datasheet_when_attachment_already_exists(self):
        result = self._run(dry_run=True, has_datasheet_attachment=True)
        ds_diff = result["diff"]["datasheet"]
        assert ds_diff["field"] == "datasheet_link"
        # When attachment exists, current shows the existing link URL
        assert ds_diff["current"] == "https://existing.com/ds.pdf"
        assert ds_diff["status"] == "skipped"

    def test_diff_price_breaks_new(self):
        result = self._run(dry_run=True, existing_pb_quantities=[])
        pb_rows = result["diff"]["price_breaks"]
        assert len(pb_rows) == 2
        assert pb_rows[0]["quantity"] == 1
        assert pb_rows[0]["incoming_price"] == 0.15
        assert pb_rows[0]["incoming_currency"] == "EUR"
        assert pb_rows[0]["status"] == "new"
        assert pb_rows[1]["quantity"] == 10
        assert pb_rows[1]["status"] == "new"

    def test_diff_price_breaks_skipped(self):
        result = self._run(dry_run=True, existing_pb_quantities=[1, 10])
        pb_rows = result["diff"]["price_breaks"]
        assert all(r["status"] == "skipped" for r in pb_rows)

    def test_diff_parameters_new(self):
        result = self._run(dry_run=True, param_exists=False)
        param_rows = result["diff"]["parameters"]
        assert len(param_rows) == 1
        assert param_rows[0]["name"] == "Voltage"
        assert param_rows[0]["units"] == "V"
        assert param_rows[0]["incoming"] == "5V"
        assert param_rows[0]["status"] == "new"
        assert param_rows[0]["current"] is None

    def test_diff_parameters_skipped(self):
        result = self._run(dry_run=True, param_exists=True)
        param_rows = result["diff"]["parameters"]
        assert param_rows[0]["status"] == "skipped"
        assert param_rows[0]["current"] == "5V"

    def test_preview_compat_arrays_unchanged(self):
        """updated/skipped/errors arrays remain backward-compatible."""
        result = self._run(dry_run=True)
        assert "image" in result["updated"]
        assert "datasheet_link" in result["updated"]
        assert "price_break:1" in result["updated"]
        assert "parameter:Voltage" in result["updated"]

    def test_diff_supplier_part_fields_when_empty(self):
        """SupplierPart description/link show as new when currently empty."""
        sp = _make_supplier_part()
        sp.description = ""
        sp.link = ""
        result = self._run(dry_run=True, supplier_part=sp)
        sp_rows = result["diff"]["supplier_part"]
        fields = {r["field"]: r for r in sp_rows}
        assert "link" in fields
        assert fields["link"]["status"] == "new"
        assert "description" in fields
        assert fields["description"]["status"] == "new"

    def test_diff_supplier_part_fields_when_already_set(self):
        """SupplierPart fields show as updated when values differ."""
        sp = _make_supplier_part()
        sp.description = "Existing description"
        sp.link = "https://existing.com"

        result = self._run(dry_run=True, supplier_part=sp)
        sp_rows = result["diff"]["supplier_part"]
        fields = {r["field"]: r for r in sp_rows}
        assert fields["link"]["status"] == "updated"
        assert fields["link"]["current"] == "https://existing.com"
        assert fields["description"]["status"] == "updated"
        assert fields["description"]["current"] == "Existing description"

    def test_diff_supplier_part_fields_skipped_when_matching(self):
        """SupplierPart fields show as skipped when values already match."""
        sp = _make_supplier_part()
        sp.description = _FRESH_DATA.description
        sp.link = _FRESH_DATA.link

        result = self._run(dry_run=True, supplier_part=sp)
        sp_rows = result["diff"]["supplier_part"]
        fields = {r["field"]: r for r in sp_rows}
        assert fields["link"]["status"] == "skipped"
        assert fields["description"]["status"] == "skipped"

    def test_supplier_part_updated_on_apply(self):
        """SupplierPart.save() is called with new field values."""
        from inventree_import_plugin.services.enrich import enrich_part_for_provider

        plugin = _MockCorePlugin()
        sp = _make_supplier_part()
        sp.description = ""
        sp.link = ""

        with (
            patch(_SVC_PART) as MockPart,
            patch(_SVC_SP) as MockSP,
            patch(_SVC_PB) as MockPB,
            patch(_SVC_CT) as MockContentType,
            patch(_SVC_TMPL) as MockTmpl,
            patch(_SVC_PARAM) as MockParam,
            patch(_SVC_DL),
            patch(_SVC_ATTACH) as MockAttach,
            patch.object(plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _make_part()
            MockContentType.objects.get_for_model.return_value = "part-content-type"
            _svc_stub_qs_for_sp(MockSP, sp)
            _svc_stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment(MockAttach, has_datasheet=False)

            result = enrich_part_for_provider(plugin, "test-provider", 42, dry_run=False)

        sp.save.assert_called_once()
        assert sp.description == _FRESH_DATA.description
        assert sp.link == _FRESH_DATA.link

    def test_supplier_part_available_updated_on_apply(self):
        """SupplierPart availability uses the model helper when stock changes."""
        from inventree_import_plugin.services.enrich import enrich_part_for_provider

        plugin = _MockCorePlugin()
        sp = _make_supplier_part()
        sp.description = _FRESH_DATA.description
        sp.link = _FRESH_DATA.link
        sp.available = 10

        stock_data = PartData(
            sku=_FRESH_DATA.sku,
            name=_FRESH_DATA.name,
            description=_FRESH_DATA.description,
            manufacturer_name=_FRESH_DATA.manufacturer_name,
            manufacturer_part_number=_FRESH_DATA.manufacturer_part_number,
            link=_FRESH_DATA.link,
            image_url=_FRESH_DATA.image_url,
            datasheet_url=_FRESH_DATA.datasheet_url,
            price_breaks=_FRESH_DATA.price_breaks,
            parameters=_FRESH_DATA.parameters,
            extra_data={"stock": 250},
        )

        with (
            patch(_SVC_PART) as MockPart,
            patch(_SVC_SP) as MockSP,
            patch(_SVC_PB) as MockPB,
            patch(_SVC_CT) as MockContentType,
            patch(_SVC_TMPL) as MockTmpl,
            patch(_SVC_PARAM) as MockParam,
            patch(_SVC_DL),
            patch(_SVC_ATTACH) as MockAttach,
            patch.object(plugin, "get_import_data", return_value=stock_data),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _make_part()
            MockContentType.objects.get_for_model.return_value = "part-content-type"
            _svc_stub_qs_for_sp(MockSP, sp)
            _svc_stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment(MockAttach, has_datasheet=False)

            result = enrich_part_for_provider(plugin, "test-provider", 42, dry_run=False)

        assert "supplier_part:available" in result["updated"]
        sp.update_available_quantity.assert_called_once_with(250)


# ---------------------------------------------------------------------------
# supplier_part_defaults unit tests
# ---------------------------------------------------------------------------


class TestSupplierPartDefaults:
    def test_includes_link(self) -> None:
        from inventree_import_plugin.base import supplier_part_defaults

        data = PartData(sku="C1", name="X", description="", link="https://lcsc.com/C1")
        defaults = supplier_part_defaults(data)
        assert defaults["link"] == "https://lcsc.com/C1"

    def test_includes_description_when_present(self) -> None:
        from inventree_import_plugin.base import supplier_part_defaults

        data = PartData(sku="C1", name="X", description="Op-amp")
        defaults = supplier_part_defaults(data)
        assert defaults["description"] == "Op-amp"

    def test_omits_description_when_empty(self) -> None:
        from inventree_import_plugin.base import supplier_part_defaults

        data = PartData(sku="C1", name="X", description="")
        defaults = supplier_part_defaults(data)
        assert "description" not in defaults

    def test_includes_available_when_stock_positive(self) -> None:
        from inventree_import_plugin.base import supplier_part_defaults

        data = PartData(sku="C1", name="X", description="", extra_data={"stock": 500})
        defaults = supplier_part_defaults(data)
        assert defaults["available"] == 500
        # availability_updated is handled by the model's save(), not set in defaults

    def test_omits_available_when_stock_zero(self) -> None:
        from inventree_import_plugin.base import supplier_part_defaults

        data = PartData(sku="C1", name="X", description="", extra_data={"stock": 0})
        defaults = supplier_part_defaults(data)
        assert "available" not in defaults
        assert "availability_updated" not in defaults

    def test_omits_available_when_no_stock_key(self) -> None:
        from inventree_import_plugin.base import supplier_part_defaults

        data = PartData(sku="C1", name="X", description="")
        defaults = supplier_part_defaults(data)
        assert "available" not in defaults

    def test_omits_available_when_stock_not_int(self) -> None:
        from inventree_import_plugin.base import supplier_part_defaults

        data = PartData(sku="C1", name="X", description="", extra_data={"stock": "many"})
        defaults = supplier_part_defaults(data)
        assert "available" not in defaults


# ---------------------------------------------------------------------------
# Part description/link filling from supplier data
# ---------------------------------------------------------------------------


class TestPartFieldFillingBaseEnrich:
    """Part description/link filled from supplier data when empty (base._enrich_part)."""

    _DL_PATCH = "inventree_import_plugin.base._download_and_set_image"

    def _run(self, plugin, *, part=None, fresh_data=None, dry_run=False):
        _part = part or _make_part()
        _sp = _make_supplier_part()
        _fresh = fresh_data or _FRESH_DATA

        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch(_PT_PB) as MockPB,
            patch(_PT_CT) as MockContentType,
            patch(_PT_TMPL) as MockTmpl,
            patch(_PT_PARAM) as MockParam,
            patch(_PT_ATTACH) as MockAttach,
            patch(self._DL_PATCH),
            patch.object(plugin, "get_import_data", return_value=_fresh),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _part
            MockContentType.objects.get_for_model.return_value = "part-content-type"
            _stub_qs_for_sp(MockSP, _sp)
            _stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment_for_base(MockAttach, has_datasheet=True)

            return plugin._enrich_part(42, dry_run=dry_run)

    def test_description_filled_when_empty(self, mouser_plugin: MouserImportPlugin) -> None:
        part = _make_part(description="", link="https://already.set")
        result = self._run(mouser_plugin, part=part)
        assert "part:description" in result["updated"]
        assert part.description == _FRESH_DATA.description

    def test_link_filled_when_empty(self, mouser_plugin: MouserImportPlugin) -> None:
        part = _make_part(description="Already set", link="")
        result = self._run(mouser_plugin, part=part)
        assert "part:link" in result["updated"]
        assert part.link == _FRESH_DATA.link

    def test_both_filled_when_empty(self, mouser_plugin: MouserImportPlugin) -> None:
        part = _make_part(description="", link="")
        result = self._run(mouser_plugin, part=part)
        assert "part:description" in result["updated"]
        assert "part:link" in result["updated"]
        assert part.description == _FRESH_DATA.description
        assert part.link == _FRESH_DATA.link
        part.save.assert_called_once()

    def test_not_overwritten_when_already_set(self, mouser_plugin: MouserImportPlugin) -> None:
        part = _make_part(description="Keep this", link="https://keep.this")
        result = self._run(mouser_plugin, part=part)
        assert "part:description" not in result["updated"]
        assert "part:link" not in result["updated"]
        assert part.description == "Keep this"
        assert part.link == "https://keep.this"

    def test_preview_reports_without_saving(self, mouser_plugin: MouserImportPlugin) -> None:
        part = _make_part(description="", link="")
        result = self._run(mouser_plugin, part=part, dry_run=True)
        assert "part:description" in result["updated"]
        assert "part:link" in result["updated"]
        part.save.assert_not_called()


class TestPartFieldFillingSvcEnrich:
    """Part description/link filled from supplier data when empty (enrich_part_for_provider)."""

    def _run(self, *, part=None, fresh_data=None, dry_run=True):
        from inventree_import_plugin.services.enrich import enrich_part_for_provider

        plugin = _MockCorePlugin()
        _part = part or _make_part()
        _sp = _make_supplier_part()
        _fresh = fresh_data or _FRESH_DATA

        with (
            patch(_SVC_PART) as MockPart,
            patch(_SVC_SP) as MockSP,
            patch(_SVC_PB) as MockPB,
            patch(_SVC_CT) as MockContentType,
            patch(_SVC_TMPL) as MockTmpl,
            patch(_SVC_PARAM) as MockParam,
            patch(_SVC_DL),
            patch(_SVC_ATTACH) as MockAttach,
            patch.object(plugin, "get_import_data", return_value=_fresh),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _part
            MockContentType.objects.get_for_model.return_value = "part-content-type"
            _svc_stub_qs_for_sp(MockSP, _sp)
            _svc_stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment(MockAttach, has_datasheet=True)

            return enrich_part_for_provider(plugin, "test-provider", 42, dry_run=dry_run)

    def test_description_filled_on_apply(self) -> None:
        part = _make_part(description="", link="https://already.set")
        result = self._run(part=part, dry_run=False)
        assert "part:description" in result["updated"]
        assert part.description == _FRESH_DATA.description

    def test_link_filled_on_apply(self) -> None:
        part = _make_part(description="Already set", link="")
        result = self._run(part=part, dry_run=False)
        assert "part:link" in result["updated"]
        assert part.link == _FRESH_DATA.link

    def test_not_overwritten_on_apply(self) -> None:
        part = _make_part(description="Keep this", link="https://keep.this")
        result = self._run(part=part, dry_run=False)
        assert "part:description" not in result["updated"]
        assert "part:link" not in result["updated"]

    def test_preview_reports_part_fields(self) -> None:
        part = _make_part(description="", link="")
        result = self._run(part=part, dry_run=True)
        assert "part:description" in result["updated"]
        assert "part:link" in result["updated"]

    def test_diff_part_fields_when_empty(self) -> None:
        result = self._run(part=_make_part(description="", link=""), dry_run=True)
        rows = result["diff"]["part_fields"]
        fields = {r["field"]: r for r in rows}
        assert fields["description"]["status"] == "new"
        assert fields["link"]["status"] == "new"

    def test_diff_part_fields_skipped_when_set(self) -> None:
        result = self._run(
            part=_make_part(description="Exists", link="https://exists.com"),
            dry_run=True,
        )
        rows = result["diff"]["part_fields"]
        fields = {r["field"]: r for r in rows}
        assert fields["description"]["status"] == "skipped"
        assert fields["link"]["status"] == "skipped"


# ---------------------------------------------------------------------------
# SupplierPart parameter mirroring
# ---------------------------------------------------------------------------


class TestSupplierPartParameterMirrorBaseEnrich:
    """SupplierPart gets parameters mirrored when using generic parameter model."""

    _DL_PATCH = "inventree_import_plugin.base._download_and_set_image"

    def _run(self, plugin, *, param_exists=False, dry_run=False):
        _part = _make_part(description="Set", link="https://set.com")
        _sp = _make_supplier_part()

        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch(_PT_PB) as MockPB,
            patch(_PT_CT) as MockContentType,
            patch(_PT_TMPL) as MockTmpl,
            patch(_PT_PARAM) as MockParam,
            patch(_PT_ATTACH) as MockAttach,
            patch(self._DL_PATCH),
            patch.object(plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _part
            MockContentType.objects.get_for_model.return_value = "part-content-type"
            _stub_qs_for_sp(MockSP, _sp)
            _stub_pb_qs(MockPB, [])
            template_mock = MagicMock()
            MockTmpl.objects.get_or_create.return_value = (template_mock, True)
            MockParam.objects.filter.return_value.exists.return_value = param_exists
            _stub_attachment_for_base(MockAttach, has_datasheet=True)

            return plugin._enrich_part(42, dry_run=dry_run)

    def test_sp_parameter_created_when_not_present(self, mouser_plugin: MouserImportPlugin) -> None:
        result = self._run(mouser_plugin, param_exists=False)
        assert "supplier_parameter:Voltage" in result["updated"]

    def test_sp_parameter_skipped_when_present(self, mouser_plugin: MouserImportPlugin) -> None:
        result = self._run(mouser_plugin, param_exists=True)
        assert "supplier_parameter:Voltage" in result["skipped"]

    def test_sp_parameter_preview_no_create(self, mouser_plugin: MouserImportPlugin) -> None:
        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch(_PT_PB) as MockPB,
            patch(_PT_CT) as MockContentType,
            patch(_PT_TMPL) as MockTmpl,
            patch(_PT_PARAM) as MockParam,
            patch(_PT_ATTACH) as MockAttach,
            patch(self._DL_PATCH),
            patch.object(mouser_plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _make_part(
                description="Set", link="https://set.com"
            )
            MockContentType.objects.get_for_model.return_value = "part-content-type"
            _stub_qs_for_sp(MockSP, _make_supplier_part())
            _stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment_for_base(MockAttach, has_datasheet=True)

            result = mouser_plugin._enrich_part(42, dry_run=True)

        assert "supplier_parameter:Voltage" in result["updated"]
        MockParam.objects.create.assert_not_called()


class TestSupplierPartParameterMirrorSvcEnrich:
    """SupplierPart gets parameters mirrored in enrich_part_for_provider."""

    def _run(self, *, param_exists=False, dry_run=True):
        from inventree_import_plugin.services.enrich import enrich_part_for_provider

        plugin = _MockCorePlugin()
        _part = _make_part(description="Set", link="https://set.com")
        _sp = _make_supplier_part()

        with (
            patch(_SVC_PART) as MockPart,
            patch(_SVC_SP) as MockSP,
            patch(_SVC_PB) as MockPB,
            patch(_SVC_CT) as MockContentType,
            patch(_SVC_TMPL) as MockTmpl,
            patch(_SVC_PARAM) as MockParam,
            patch(_SVC_DL),
            patch(_SVC_ATTACH) as MockAttach,
            patch.object(plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _part
            MockContentType.objects.get_for_model.return_value = "part-content-type"
            _svc_stub_qs_for_sp(MockSP, _sp)
            _svc_stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = param_exists
            MockParam.objects.filter.return_value.first.return_value = (
                MagicMock(data="5V") if param_exists else None
            )
            _stub_attachment(MockAttach, has_datasheet=True)

            return enrich_part_for_provider(plugin, "test-provider", 42, dry_run=dry_run)

    def test_sp_parameter_updated_when_new(self) -> None:
        result = self._run(param_exists=False, dry_run=True)
        assert "supplier_parameter:Voltage" in result["updated"]

    def test_sp_parameter_skipped_when_exists(self) -> None:
        result = self._run(param_exists=True, dry_run=True)
        assert "supplier_parameter:Voltage" in result["skipped"]

    def test_sp_parameter_created_on_apply(self) -> None:
        result = self._run(param_exists=False, dry_run=False)
        assert "supplier_parameter:Voltage" in result["updated"]


# ---------------------------------------------------------------------------
# _key_allowed helper
# ---------------------------------------------------------------------------


class TestKeyAllowed:
    def test_none_allows_all(self) -> None:
        from inventree_import_plugin.services.enrich import _key_allowed

        assert _key_allowed("anything", None) is True

    def test_matching_key_allowed(self) -> None:
        from inventree_import_plugin.services.enrich import _key_allowed

        assert _key_allowed("image", {"image", "datasheet_link"}) is True

    def test_non_matching_key_blocked(self) -> None:
        from inventree_import_plugin.services.enrich import _key_allowed

        assert _key_allowed("image", {"datasheet_link"}) is False

    def test_empty_set_blocks_all(self) -> None:
        from inventree_import_plugin.services.enrich import _key_allowed

        assert _key_allowed("image", set()) is False


# ---------------------------------------------------------------------------
# enrich_part_for_provider with selected_keys (partial apply)
# ---------------------------------------------------------------------------


_SVC_GPA = "inventree_import_plugin.services.enrich.get_provider_adapters"


class TestSelectedKeysApply:
    """Test that selected_keys gates which writes happen during apply."""

    def _run(
        self,
        *,
        selected_keys: set[str] | None = None,
        part=None,
    ):
        from inventree_import_plugin.services.enrich import enrich_part_for_provider

        plugin = _MockCorePlugin()
        _part = part or _make_part()
        _sp = _make_supplier_part()

        with (
            patch(_SVC_PART) as MockPart,
            patch(_SVC_SP) as MockSP,
            patch(_SVC_PB) as MockPB,
            patch(_SVC_CT) as MockContentType,
            patch(_SVC_TMPL) as MockTmpl,
            patch(_SVC_PARAM) as MockParam,
            patch(_SVC_DL) as MockDL,
            patch(_SVC_ATTACH) as MockAttach,
            patch.object(plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _part
            MockContentType.objects.get_for_model.return_value = "part-content-type"
            _svc_stub_qs_for_sp(MockSP, _sp)
            _svc_stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment(MockAttach, has_datasheet=False)

            return enrich_part_for_provider(
                plugin,
                "test-provider",
                42,
                dry_run=False,
                selected_keys=selected_keys,
            )

    def test_none_selected_keys_applies_all(self) -> None:
        """selected_keys=None (default) applies everything — backward-compatible."""
        result = self._run(selected_keys=None)
        assert "image" in result["updated"]
        assert "datasheet_link" in result["updated"]
        assert any(k.startswith("price_break:") for k in result["updated"])
        assert any(k.startswith("parameter:") for k in result["updated"])

    def test_image_only(self) -> None:
        result = self._run(selected_keys={"image"})
        assert "image" in result["updated"]
        assert "datasheet_link" not in result["updated"]
        assert all(not k.startswith("price_break:") for k in result["updated"])

    def test_datasheet_only(self) -> None:
        result = self._run(selected_keys={"datasheet_link"})
        assert "datasheet_link" in result["updated"]
        assert "image" not in result["updated"]

    def test_price_breaks_only(self) -> None:
        result = self._run(selected_keys={"price_break:1", "price_break:10"})
        pb_updated = [k for k in result["updated"] if k.startswith("price_break:")]
        assert len(pb_updated) == 2
        assert "image" not in result["updated"]

    def test_parameter_only(self) -> None:
        result = self._run(selected_keys={"parameter:Voltage"})
        assert "parameter:Voltage" in result["updated"]
        assert "image" not in result["updated"]
        assert "datasheet_link" not in result["updated"]

    def test_empty_set_applies_nothing(self) -> None:
        result = self._run(selected_keys=set())
        assert result["updated"] == []
        assert all(k in result["skipped"] for k in ["image", "datasheet_link"])

    def test_part_field_gated(self) -> None:
        part = _make_part(description="", link="")
        result = self._run(selected_keys={"part:description"}, part=part)
        assert "part:description" in result["updated"]
        assert "part:link" not in result["updated"]

    def test_supplier_part_gated(self) -> None:
        result = self._run(selected_keys={"supplier_part:link"})
        sp_updated = [k for k in result["updated"] if k.startswith("supplier_part:")]
        assert sp_updated == ["supplier_part:link"]


# ---------------------------------------------------------------------------
# parse_bulk_operations
# ---------------------------------------------------------------------------


def _make_adapter(slug: str = "test-provider") -> MagicMock:
    adapter = MagicMock()
    adapter.definition.slug = slug
    return adapter


class TestParseBulkOperations:
    def _make_request(self, operations):
        request = MagicMock()
        request.data = {"operations": operations}
        return request

    def _make_plugin(self, batch_size=50):
        plugin = MagicMock()
        plugin.get_setting.return_value = batch_size
        return plugin

    def test_valid_operations(self) -> None:
        from inventree_import_plugin.services.enrich import parse_bulk_operations

        plugin = self._make_plugin()
        request = self._make_request(
            [
                {"part_id": 1, "provider_slug": "test-provider", "selected_keys": ["image"]},
                {"part_id": 2, "provider_slug": "test-provider"},
            ]
        )
        with patch(_SVC_GPA, return_value=(_make_adapter("test-provider"),)):
            result = parse_bulk_operations(plugin, request)

        assert len(result) == 2
        assert result[0]["part_id"] == 1
        assert result[0]["selected_keys"] == {"image"}
        assert result[1]["part_id"] == 2
        assert result[1]["selected_keys"] is None

    def test_missing_operations_key_raises(self) -> None:
        from inventree_import_plugin.services.enrich import parse_bulk_operations

        plugin = self._make_plugin()
        request = MagicMock()
        request.data = {}
        with pytest.raises(ValueError, match="operations is required"):
            parse_bulk_operations(plugin, request)

    def test_empty_operations_raises(self) -> None:
        from inventree_import_plugin.services.enrich import parse_bulk_operations

        plugin = self._make_plugin()
        request = self._make_request([])
        with patch(_SVC_GPA, return_value=(_make_adapter("test-provider"),)):
            with pytest.raises(ValueError, match="At least one operation"):
                parse_bulk_operations(plugin, request)

    def test_batch_size_exceeded(self) -> None:
        from inventree_import_plugin.services.enrich import parse_bulk_operations

        plugin = self._make_plugin(batch_size=2)
        ops = [{"part_id": i, "provider_slug": "test-provider"} for i in range(1, 4)]
        request = self._make_request(ops)
        with patch(_SVC_GPA, return_value=(_make_adapter("test-provider"),)):
            with pytest.raises(ValueError, match="Too many operations"):
                parse_bulk_operations(plugin, request)

    def test_invalid_provider_slug_raises(self) -> None:
        from inventree_import_plugin.services.enrich import parse_bulk_operations

        plugin = self._make_plugin()
        request = self._make_request(
            [
                {"part_id": 1, "provider_slug": "no-such-provider"},
            ]
        )
        with patch(_SVC_GPA, return_value=(_make_adapter("test-provider"),)):
            with pytest.raises(ValueError, match="Invalid provider slug"):
                parse_bulk_operations(plugin, request)

    def test_missing_part_id_raises(self) -> None:
        from inventree_import_plugin.services.enrich import parse_bulk_operations

        plugin = self._make_plugin()
        request = self._make_request(
            [
                {"provider_slug": "test-provider"},
            ]
        )
        with patch(_SVC_GPA, return_value=(_make_adapter("test-provider"),)):
            with pytest.raises(ValueError, match="part_id"):
                parse_bulk_operations(plugin, request)

    def test_missing_provider_slug_raises(self) -> None:
        from inventree_import_plugin.services.enrich import parse_bulk_operations

        plugin = self._make_plugin()
        request = self._make_request(
            [
                {"part_id": 1},
            ]
        )
        with patch(_SVC_GPA, return_value=(_make_adapter("test-provider"),)):
            with pytest.raises(ValueError, match="provider_slug"):
                parse_bulk_operations(plugin, request)

    def test_selected_keys_converted_to_set(self) -> None:
        from inventree_import_plugin.services.enrich import parse_bulk_operations

        plugin = self._make_plugin()
        request = self._make_request(
            [
                {
                    "part_id": 1,
                    "provider_slug": "test-provider",
                    "selected_keys": ["image", "datasheet_link"],
                },
            ]
        )
        with patch(_SVC_GPA, return_value=(_make_adapter("test-provider"),)):
            result = parse_bulk_operations(plugin, request)

        assert result[0]["selected_keys"] == {"image", "datasheet_link"}

    def test_selected_keys_none_when_absent(self) -> None:
        from inventree_import_plugin.services.enrich import parse_bulk_operations

        plugin = self._make_plugin()
        request = self._make_request(
            [
                {"part_id": 1, "provider_slug": "test-provider"},
            ]
        )
        with patch(_SVC_GPA, return_value=(_make_adapter("test-provider"),)):
            result = parse_bulk_operations(plugin, request)

        assert result[0]["selected_keys"] is None


# ---------------------------------------------------------------------------
# bulk_enrich with operations parameter
# ---------------------------------------------------------------------------


class TestBulkEnrichOperations:
    """Test bulk_enrich with explicit operations list."""

    def _run(self, operations, *, dry_run=False):
        from inventree_import_plugin.services.enrich import bulk_enrich

        plugin = _MockCorePlugin()
        _part = _make_part()
        _sp = _make_supplier_part()

        with (
            patch(_SVC_PART) as MockPart,
            patch(_SVC_SP) as MockSP,
            patch(_SVC_PB) as MockPB,
            patch(_SVC_CT) as MockContentType,
            patch(_SVC_TMPL) as MockTmpl,
            patch(_SVC_PARAM) as MockParam,
            patch(_SVC_DL),
            patch(_SVC_ATTACH) as MockAttach,
            patch.object(plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _part
            MockContentType.objects.get_for_model.return_value = "part-content-type"
            _svc_stub_qs_for_sp(MockSP, _sp)
            _svc_stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment(MockAttach, has_datasheet=False)

            return bulk_enrich(plugin, dry_run=dry_run, operations=operations)

    def test_operations_with_selected_keys(self) -> None:
        result = self._run(
            operations=[
                {
                    "part_id": 1,
                    "provider_slug": "test-provider",
                    "selected_keys": {"image"},
                },
            ],
            dry_run=False,
        )
        assert result["summary"]["operations"] == 1
        r = result["results"][0]
        assert "image" in r["updated"]
        assert "datasheet_link" not in r["updated"]

    def test_operations_without_selected_keys(self) -> None:
        result = self._run(
            operations=[
                {"part_id": 1, "provider_slug": "test-provider", "selected_keys": None},
            ],
            dry_run=False,
        )
        r = result["results"][0]
        assert "image" in r["updated"]
        assert "datasheet_link" in r["updated"]

    def test_legacy_path_still_works(self) -> None:
        """Ensure backward-compatible legacy path via part_ids + provider_slugs."""
        from inventree_import_plugin.services.enrich import bulk_enrich

        plugin = _MockCorePlugin()
        _part = _make_part()
        _sp = _make_supplier_part()

        with (
            patch(_SVC_PART) as MockPart,
            patch(_SVC_SP) as MockSP,
            patch(_SVC_PB) as MockPB,
            patch(_SVC_CT) as MockContentType,
            patch(_SVC_TMPL) as MockTmpl,
            patch(_SVC_PARAM) as MockParam,
            patch(_SVC_DL),
            patch(_SVC_ATTACH) as MockAttach,
            patch.object(plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = _part
            MockContentType.objects.get_for_model.return_value = "part-content-type"
            _svc_stub_qs_for_sp(MockSP, _sp)
            _svc_stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False
            _stub_attachment(MockAttach, has_datasheet=False)

            result = bulk_enrich(plugin, [1], ["test-provider"], dry_run=False)

        assert result["summary"]["operations"] == 1
        r = result["results"][0]
        assert "image" in r["updated"]
