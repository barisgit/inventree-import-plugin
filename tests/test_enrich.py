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
_PT_CT = "django.contrib.contenttypes.models.ContentType"
_PT_TMPL = "common.models.ParameterTemplate"
_PT_PARAM = "common.models.Parameter"


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

            result = mouser_plugin._enrich_part(42)

        assert "image" in result["skipped"]
        mock_dl.assert_not_called()

    def test_datasheet_link_updated_when_empty(self, mouser_plugin: MouserImportPlugin) -> None:
        part = _make_part(link="")
        result = self._run(mouser_plugin, part=part)
        assert "datasheet_link" in result["updated"]
        assert part.link == _FRESH_DATA.datasheet_url

    def test_datasheet_link_skipped_when_already_set(
        self, mouser_plugin: MouserImportPlugin
    ) -> None:
        part = _make_part(link="https://existing.com/ds.pdf")
        result = self._run(mouser_plugin, part=part)
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

            result = mouser_plugin._enrich_part(42, dry_run=True)

        assert "image" in result["updated"]
        # Image download must NOT have been called in dry_run mode
        mock_dl.assert_not_called()

    def test_preview_does_not_save_datasheet(self, mouser_plugin: MouserImportPlugin) -> None:
        part = _make_part(link="")
        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch(_PT_PB) as MockPB,
            patch(_PT_CT) as MockContentType,
            patch(_PT_TMPL) as MockTmpl,
            patch(_PT_PARAM) as MockParam,
            patch(self._DL_PATCH),
            patch.object(mouser_plugin, "get_import_data", return_value=_FRESH_DATA),
        ):
            MockPart.DoesNotExist = Exception
            MockPart.objects.get.return_value = part
            MockContentType.objects.get_for_model.return_value = "ct"
            _stub_qs_for_sp(MockSP, _make_supplier_part())
            _stub_pb_qs(MockPB, [])
            MockTmpl.objects.get_or_create.return_value = (MagicMock(), True)
            MockParam.objects.filter.return_value.exists.return_value = False

            result = mouser_plugin._enrich_part(42, dry_run=True)

        assert "datasheet_link" in result["updated"]
        # part.save must NOT have been called in dry_run
        part.save.assert_not_called()

    def test_preview_does_not_create_price_breaks(self, mouser_plugin: MouserImportPlugin) -> None:
        with (
            patch(_PT_PART) as MockPart,
            patch(_PT_SP) as MockSP,
            patch(_PT_PB) as MockPB,
            patch(_PT_CT) as MockContentType,
            patch(_PT_TMPL) as MockTmpl,
            patch(_PT_PARAM) as MockParam,
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

        with patch.dict(
            sys.modules, {"InvenTree": inventree_mod, "InvenTree.helpers_model": helper_mod}
        ):
            from inventree_import_plugin.base import _download_and_set_image as fn

            fn(part, "https://example.com/test.jpg")

        part.image.save.assert_called_once()
        args, kwargs = part.image.save.call_args
        assert args[0].startswith("part_")
        assert args[0].endswith(".png")
        assert kwargs == {"save": True}
        helper_mod.download_image_from_url.assert_called_once_with("https://example.com/test.jpg")

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


class TestEnrichPartForProviderDiff:
    """Test enrich_part_for_provider returns structured diff in preview mode."""

    def _run(self, *, dry_run=True, existing_pb_quantities=None, param_exists=False, part=None):
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
            patch(_SVC_DL),
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
        assert set(diff.keys()) == {"image", "datasheet", "price_breaks", "parameters"}

    def test_diff_image_when_part_has_no_image(self):
        result = self._run(dry_run=True, part=_make_part(image=""))
        image_diff = result["diff"]["image"]
        assert image_diff["field"] == "image"
        assert image_diff["current"] is None
        assert image_diff["incoming"] == _FRESH_DATA.image_url

    def test_diff_image_when_part_already_has_image(self):
        result = self._run(dry_run=True, part=_make_part(image="existing.jpg"))
        image_diff = result["diff"]["image"]
        assert image_diff["current"] == "existing.jpg"

    def test_diff_datasheet_when_part_has_no_link(self):
        result = self._run(dry_run=True, part=_make_part(link=""))
        ds_diff = result["diff"]["datasheet"]
        assert ds_diff["field"] == "datasheet_link"
        assert ds_diff["current"] is None
        assert ds_diff["incoming"] == _FRESH_DATA.datasheet_url

    def test_diff_datasheet_when_part_already_has_link(self):
        result = self._run(dry_run=True, part=_make_part(link="https://old.com/ds.pdf"))
        ds_diff = result["diff"]["datasheet"]
        assert ds_diff["current"] == "https://old.com/ds.pdf"

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
