"""Tests for AliExpress HTML-only supplier integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests as _requests

from inventree_import_plugin.compat import SearchResult
from inventree_import_plugin.models import PartData, PartParameter, PriceBreak
from inventree_import_plugin.providers.aliexpress import AliExpressProvider
from inventree_import_plugin.suppliers.aliexpress import (
    _build_part_data,
    _clean_title,
    _extract_content_language,
    _is_generic_description,
    _parse_embedded_data,
    _parse_meta_tags,
    _parse_parameters,
    _parse_price_breaks,
    _parse_stock,
    extract_product_id,
    fetch_aliexpress_part,
)

# ---------------------------------------------------------------------------
# Fixture HTML
# ---------------------------------------------------------------------------

PRODUCT_ID = "1005006274946353"
PRODUCT_URL = f"https://www.aliexpress.com/item/{PRODUCT_ID}.html"
PRODUCT_URL_DASH_SLUG = f"https://www.aliexpress.com/item/-/{PRODUCT_ID}.html"
PRODUCT_URL_US = f"https://www.aliexpress.us/item/{PRODUCT_ID}.html"
PRODUCT_URL_DE = f"https://de.aliexpress.com/item/{PRODUCT_ID}.html"

_FIXTURE_HTML = (
    "<!DOCTYPE html><html><head>"
    '<meta property="og:title" content="ESP32 Development Board WiFi+Bluetooth">'
    '<meta property="og:image" content="https://ae01.alicdn.com/kf/S123.jpg">'
    '<meta property="og:description" content="ESP32 Dual Core MCU Module">'
    "</head><body>"
    '<script>window._d_c_.DCData({"titleModule":{"subject":"ESP32 Development Board"},'
    '"priceModule":{"minAmount":"3.99","currency":"USD",'
    '"prices":[{"min":1,"max":9,"price":"3.99"},'
    '{"min":10,"max":49,"price":"3.49"},'
    '{"min":50,"max":999,"price":"2.99"}]},'
    '"specsModule":{"props":['
    '{"attrName":"Brand Name","attrValue":"ESPRESSIF"},'
    '{"attrName":"Operating Voltage","attrValue":"3.3V"}]},'
    '"quantityModule":{"totalAvail":1580}})</script>'
    "</body></html>"
)

_FIXTURE_HTML_ASSIGN = (
    "<!DOCTYPE html><html><head>"
    '<meta property="og:title" content="STM32F103 Blue Pill Board">'
    '<meta property="og:image" content="https://ae01.alicdn.com/kf/STM32.jpg">'
    '<meta property="og:description" content="STM32F103C8T6 Mini Development Board">'
    "</head><body>"
    "<script>window._d_c_.DCData = "
    '{"titleModule":{"subject":"STM32F103 Blue Pill Board"},'
    '"priceModule":{"minAmount":"2.49","currency":"USD",'
    '"prices":[{"min":1,"max":4,"price":"2.49"},'
    '{"min":5,"max":19,"price":"2.09"}]},'
    '"specsModule":{"props":['
    '{"attrName":"Brand Name","attrValue":"Generic"},'
    '{"attrName":"MCU Model","attrValue":"STM32F103C8T6"}]},'
    '"quantityModule":{"totalAvail":742}};</script>'
    "</body></html>"
)

_FIXTURE_HTML_NO_EMBEDDED = (
    "<!DOCTYPE html><html><head>"
    '<meta property="og:title" content="Basic Product">'
    '<meta property="og:image" content="https://ae01.alicdn.com/kf/basic.jpg">'
    '<meta property="og:description" content="A basic product">'
    "</head><body></body></html>"
)

_FIXTURE_HTML_NO_TITLE = (
    "<!DOCTYPE html><html><head>"
    '<meta property="og:image" content="https://ae01.alicdn.com/kf/img.jpg">'
    "</head><body></body></html>"
)

_FIXTURE_HTML_TITLE_SUFFIX = (
    "<!DOCTYPE html><html><head>"
    '<meta property="og:title" content="ESP32 Dev Board - AliExpress 7">'
    '<meta property="og:image" content="https://ae01.alicdn.com/kf/S123.jpg">'
    '<meta property="og:description" content="ESP32 Dual Core MCU Module">'
    "</head><body></body></html>"
)

_FIXTURE_HTML_GENERIC_DESC = (
    "<!DOCTYPE html><html><head>"
    '<meta property="og:title" content="Cool Gadget">'
    '<meta property="og:image" content="https://ae01.alicdn.com/kf/gadget.jpg">'
    '<meta property="og:description" content='
    '"Smarter Shopping, Better Living! Aliexpress.com">'
    "</head><body></body></html>"
)

_FIXTURE_HTML_GENERIC_DESC_NO_TITLE = (
    "<!DOCTYPE html><html><head>"
    '<meta property="og:image" content="https://ae01.alicdn.com/kf/gadget.jpg">'
    '<meta property="og:description" content='
    '"Smarter Shopping, Better Living! Aliexpress.com">'
    "</head><body></body></html>"
)


def _mock_response(html: str, url: str = PRODUCT_URL) -> MagicMock:
    mock = MagicMock()
    mock.text = html
    mock.url = url
    mock.raise_for_status = MagicMock()
    return mock


def _mock_plugin(**overrides: object) -> MagicMock:
    plugin = MagicMock()
    defaults: dict[str, object] = {
        "ALIEXPRESS_ENABLED": True,
        "ALIEXPRESS_SUPPLIER": 303,
        "ALIEXPRESS_DOWNLOAD_IMAGES": True,
    }
    defaults.update(overrides)
    plugin.get_setting = lambda key, default=None: defaults.get(key, default)
    return plugin


# ---------------------------------------------------------------------------
# extract_product_id
# ---------------------------------------------------------------------------


class TestExtractProductId:
    def test_standard_url(self) -> None:
        assert extract_product_id(PRODUCT_URL) == PRODUCT_ID

    def test_dash_slug_url(self) -> None:
        assert extract_product_id(PRODUCT_URL_DASH_SLUG) == PRODUCT_ID

    def test_us_domain(self) -> None:
        assert extract_product_id(PRODUCT_URL_US) == PRODUCT_ID

    def test_localized_subdomain(self) -> None:
        assert extract_product_id(PRODUCT_URL_DE) == PRODUCT_ID

    def test_url_with_query_params(self) -> None:
        url = f"{PRODUCT_URL}?spm=abc&algo_pvid=xyz"
        assert extract_product_id(url) == PRODUCT_ID

    def test_plain_keyword_returns_none(self) -> None:
        assert extract_product_id("ESP32") is None

    def test_other_domain_returns_none(self) -> None:
        assert extract_product_id("https://example.com/item/123") is None

    def test_empty_string_returns_none(self) -> None:
        assert extract_product_id("") is None


# ---------------------------------------------------------------------------
# _parse_meta_tags
# ---------------------------------------------------------------------------


class TestParseMetaTags:
    def test_extracts_og_tags(self) -> None:
        meta = _parse_meta_tags(_FIXTURE_HTML)
        assert meta["title"] == "ESP32 Development Board WiFi+Bluetooth"
        assert meta["image"] == "https://ae01.alicdn.com/kf/S123.jpg"
        assert meta["description"] == "ESP32 Dual Core MCU Module"

    def test_content_before_property(self) -> None:
        html = '<meta content="Value" property="og:title">'
        meta = _parse_meta_tags(html)
        assert meta["title"] == "Value"

    def test_empty_html(self) -> None:
        assert _parse_meta_tags("") == {}

    def test_no_og_tags(self) -> None:
        html = "<html><head><title>Test</title></head></html>"
        assert _parse_meta_tags(html) == {}


# ---------------------------------------------------------------------------
# _parse_embedded_data
# ---------------------------------------------------------------------------


class TestParseEmbeddedData:
    def test_parses_dcdata(self) -> None:
        data = _parse_embedded_data(_FIXTURE_HTML)
        assert "priceModule" in data
        assert "specsModule" in data
        assert "quantityModule" in data

    def test_no_script_returns_empty(self) -> None:
        data = _parse_embedded_data(_FIXTURE_HTML_NO_EMBEDDED)
        assert data == {}

    def test_invalid_json_returns_empty(self) -> None:
        html = "<script>window._d_c_.DCData(not-json)</script>"
        assert _parse_embedded_data(html) == {}

    def test_bootstrap_fallback(self) -> None:
        html = '<script>window.runParams = {"priceModule":{"minAmount":"5.99"}}</script>'
        data = _parse_embedded_data(html)
        assert data.get("priceModule", {}).get("minAmount") == "5.99"

    def test_dcdata_takes_priority_over_bootstrap(self) -> None:
        html = (
            '<script>window._d_c_.DCData({"source":"dcdata"})</script>'
            '<script>window.runParams = {"source":"bootstrap"}</script>'
        )
        data = _parse_embedded_data(html)
        assert data["source"] == "dcdata"

    def test_parses_assignment_form(self) -> None:
        data = _parse_embedded_data(_FIXTURE_HTML_ASSIGN)
        assert "priceModule" in data
        assert "specsModule" in data
        assert "quantityModule" in data

    def test_assignment_form_prices_parsed(self) -> None:
        data = _parse_embedded_data(_FIXTURE_HTML_ASSIGN)
        breaks = _parse_price_breaks(data)
        assert len(breaks) == 2
        assert breaks[0] == PriceBreak(quantity=1, price=2.49, currency="USD")
        assert breaks[1] == PriceBreak(quantity=5, price=2.09, currency="USD")

    def test_assignment_form_stock_parsed(self) -> None:
        data = _parse_embedded_data(_FIXTURE_HTML_ASSIGN)
        assert _parse_stock(data) == 742

    def test_call_form_preferred_over_assignment(self) -> None:
        html = (
            '<script>window._d_c_.DCData({"source":"call"})</script>'
            '<script>window._d_c_.DCData = {"source":"assign"};</script>'
        )
        data = _parse_embedded_data(html)
        assert data["source"] == "call"

    def test_assignment_form_used_when_no_call_form(self) -> None:
        html = '<script>window._d_c_.DCData = {"source":"assign"};</script>'
        data = _parse_embedded_data(html)
        assert data["source"] == "assign"

    def test_assignment_form_invalid_json_returns_empty(self) -> None:
        html = "<script>window._d_c_.DCData = not-json;</script>"
        assert _parse_embedded_data(html) == {}


# ---------------------------------------------------------------------------
# _parse_price_breaks
# ---------------------------------------------------------------------------


class TestParsePriceBreaks:
    def test_tiered_pricing(self) -> None:
        data = _parse_embedded_data(_FIXTURE_HTML)
        breaks = _parse_price_breaks(data)
        assert len(breaks) == 3
        assert breaks[0] == PriceBreak(quantity=1, price=3.99, currency="USD")
        assert breaks[2] == PriceBreak(quantity=50, price=2.99, currency="USD")

    def test_single_price_fallback(self) -> None:
        data = {"priceModule": {"minAmount": "4.50", "currency": "EUR"}}
        breaks = _parse_price_breaks(data)
        assert breaks == [PriceBreak(quantity=1, price=4.50, currency="EUR")]

    def test_empty_module(self) -> None:
        assert _parse_price_breaks({}) == []
        assert _parse_price_breaks({"priceModule": {}}) == []

    def test_invalid_price_skipped(self) -> None:
        data = {
            "priceModule": {
                "currency": "USD",
                "prices": [
                    {"min": 1, "price": "bad"},
                    {"min": 10, "price": "2.00"},
                ],
            }
        }
        breaks = _parse_price_breaks(data)
        assert len(breaks) == 1
        assert breaks[0].quantity == 10


# ---------------------------------------------------------------------------
# _parse_parameters
# ---------------------------------------------------------------------------


class TestParseParameters:
    def test_parses_specs(self) -> None:
        data = _parse_embedded_data(_FIXTURE_HTML)
        params = _parse_parameters(data)
        assert len(params) == 2
        assert PartParameter(name="Brand Name", value="ESPRESSIF") in params
        assert PartParameter(name="Operating Voltage", value="3.3V") in params

    def test_empty_name_skipped(self) -> None:
        data = {"specsModule": {"props": [{"attrName": "", "attrValue": "X"}]}}
        assert _parse_parameters(data) == []

    def test_empty_value_skipped(self) -> None:
        data = {"specsModule": {"props": [{"attrName": "X", "attrValue": ""}]}}
        assert _parse_parameters(data) == []

    def test_missing_module(self) -> None:
        assert _parse_parameters({}) == []


# ---------------------------------------------------------------------------
# _parse_stock
# ---------------------------------------------------------------------------


class TestParseStock:
    def test_extracts_total_avail(self) -> None:
        data = _parse_embedded_data(_FIXTURE_HTML)
        assert _parse_stock(data) == 1580

    def test_zero_stock(self) -> None:
        data = {"quantityModule": {"totalAvail": 0}}
        assert _parse_stock(data) == 0

    def test_missing_module_returns_none(self) -> None:
        assert _parse_stock({}) is None

    def test_invalid_value_returns_none(self) -> None:
        data = {"quantityModule": {"totalAvail": "not-a-number"}}
        assert _parse_stock(data) is None


# ---------------------------------------------------------------------------
# _clean_title
# ---------------------------------------------------------------------------


class TestCleanTitle:
    def test_strips_aliexpress_suffix_with_number(self) -> None:
        assert _clean_title("ESP32 Dev Board - AliExpress 7") == "ESP32 Dev Board"

    def test_strips_aliexpress_suffix_without_number(self) -> None:
        assert _clean_title("Cool Item - AliExpress") == "Cool Item"

    def test_strips_with_extra_whitespace(self) -> None:
        assert _clean_title("Some Product  -  AliExpress 42  ") == "Some Product"

    def test_no_suffix_returns_unchanged(self) -> None:
        assert _clean_title("ESP32 Development Board WiFi+Bluetooth") == (
            "ESP32 Development Board WiFi+Bluetooth"
        )

    def test_aliexpress_in_middle_not_stripped(self) -> None:
        assert _clean_title("AliExpress Special Product") == "AliExpress Special Product"

    def test_empty_string_stays_empty(self) -> None:
        assert _clean_title("") == ""


# ---------------------------------------------------------------------------
# _is_generic_description
# ---------------------------------------------------------------------------


class TestIsGenericDescription:
    def test_detects_standard_boilerplate(self) -> None:
        assert _is_generic_description("Smarter Shopping, Better Living! Aliexpress.com")

    def test_detects_without_comma(self) -> None:
        assert _is_generic_description("Smarter Shopping Better Living! Aliexpress.com")

    def test_detects_case_insensitive(self) -> None:
        assert _is_generic_description("smarter shopping, better living! AliExpress.com")

    def test_rejects_real_description(self) -> None:
        assert not _is_generic_description("ESP32 Dual Core MCU Module")

    def test_rejects_empty_string(self) -> None:
        assert not _is_generic_description("")


# ---------------------------------------------------------------------------
# _build_part_data
# ---------------------------------------------------------------------------


class TestBuildPartData:
    def test_full_html(self) -> None:
        part = _build_part_data(PRODUCT_ID, _FIXTURE_HTML)
        assert part is not None
        assert part.sku == PRODUCT_ID
        assert part.name == "ESP32 Development Board WiFi+Bluetooth"
        assert part.description == "ESP32 Dual Core MCU Module"
        assert part.image_url == "https://ae01.alicdn.com/kf/S123.jpg"
        assert part.link == PRODUCT_URL
        assert len(part.price_breaks) == 3
        assert len(part.parameters) == 2
        assert part.extra_data["stock"] == 1580
        assert part.extra_data["has_price_module"] is True
        assert part.extra_data["has_specs_module"] is True
        assert part.extra_data["has_quantity_module"] is True

    def test_no_embedded_data_still_works(self) -> None:
        part = _build_part_data("999", _FIXTURE_HTML_NO_EMBEDDED)
        assert part is not None
        assert part.name == "Basic Product"
        assert part.price_breaks == []
        assert part.parameters == []
        assert "stock" not in part.extra_data
        assert part.extra_data["has_price_module"] is False
        assert part.extra_data["has_specs_module"] is False
        assert part.extra_data["has_quantity_module"] is False

    def test_no_title_returns_none(self) -> None:
        assert _build_part_data("999", _FIXTURE_HTML_NO_TITLE) is None

    def test_returns_part_data_instance(self) -> None:
        part = _build_part_data(PRODUCT_ID, _FIXTURE_HTML)
        assert isinstance(part, PartData)

    def test_title_suffix_stripped(self) -> None:
        part = _build_part_data(PRODUCT_ID, _FIXTURE_HTML_TITLE_SUFFIX)
        assert part is not None
        assert part.name == "ESP32 Dev Board"
        assert part.description == "ESP32 Dual Core MCU Module"

    def test_generic_description_left_empty(self) -> None:
        part = _build_part_data(PRODUCT_ID, _FIXTURE_HTML_GENERIC_DESC)
        assert part is not None
        assert part.name == "Cool Gadget"
        assert part.description == ""

    def test_generic_description_with_no_title_returns_none(self) -> None:
        part = _build_part_data("999", _FIXTURE_HTML_GENERIC_DESC_NO_TITLE)
        assert part is None


class TestBuildPartDataAssign:
    def test_full_html_assignment_form(self) -> None:
        part = _build_part_data("999888", _FIXTURE_HTML_ASSIGN)
        assert part is not None
        assert part.sku == "999888"
        assert part.name == "STM32F103 Blue Pill Board"
        assert part.description == "STM32F103C8T6 Mini Development Board"
        assert part.image_url == "https://ae01.alicdn.com/kf/STM32.jpg"
        assert len(part.price_breaks) == 2
        assert len(part.parameters) == 2
        assert part.extra_data["stock"] == 742
        assert part.extra_data["has_price_module"] is True
        assert part.extra_data["has_specs_module"] is True
        assert part.extra_data["has_quantity_module"] is True

    def test_returns_part_data_instance(self) -> None:
        part = _build_part_data("999888", _FIXTURE_HTML_ASSIGN)
        assert isinstance(part, PartData)


# ---------------------------------------------------------------------------
# Diagnostics in extra_data
# ---------------------------------------------------------------------------


class TestBuildPartDataDiagnostics:
    def test_final_url_defaults_to_constructed_link(self) -> None:
        part = _build_part_data("12345", _FIXTURE_HTML_NO_EMBEDDED)
        assert part is not None
        assert part.extra_data["final_url"] == ("https://www.aliexpress.com/item/12345.html")

    def test_final_url_uses_explicit_value(self) -> None:
        part = _build_part_data(
            "12345",
            _FIXTURE_HTML_NO_EMBEDDED,
            final_url="https://redirected.aliexpress.com/item/12345.html",
        )
        assert part is not None
        assert part.extra_data["final_url"] == ("https://redirected.aliexpress.com/item/12345.html")

    def test_content_language_extracted_from_html_lang(self) -> None:
        html = (
            '<!DOCTYPE html><html lang="en">'
            '<head><meta property="og:title" content="X"></head></html>'
        )
        part = _build_part_data("1", html)
        assert part is not None
        assert part.extra_data["content_language"] == "en"

    def test_content_language_empty_when_absent(self) -> None:
        part = _build_part_data("999", _FIXTURE_HTML_NO_EMBEDDED)
        assert part is not None
        assert part.extra_data["content_language"] == ""

    def test_modules_present_flags_true(self) -> None:
        part = _build_part_data(PRODUCT_ID, _FIXTURE_HTML)
        assert part is not None
        assert part.extra_data["has_price_module"] is True
        assert part.extra_data["has_specs_module"] is True
        assert part.extra_data["has_quantity_module"] is True

    def test_modules_present_flags_false(self) -> None:
        part = _build_part_data("999", _FIXTURE_HTML_NO_EMBEDDED)
        assert part is not None
        assert part.extra_data["has_price_module"] is False
        assert part.extra_data["has_specs_module"] is False
        assert part.extra_data["has_quantity_module"] is False

    def test_stock_only_set_when_quantity_module_present(self) -> None:
        part = _build_part_data("999", _FIXTURE_HTML_NO_EMBEDDED)
        assert part is not None
        assert "stock" not in part.extra_data

    def test_no_description_fallback_to_title(self) -> None:
        """Description stays empty when generic — no fallback to title."""
        part = _build_part_data(PRODUCT_ID, _FIXTURE_HTML_GENERIC_DESC)
        assert part is not None
        assert part.description == ""


class TestExtractContentLanguage:
    def test_extracts_html_lang(self) -> None:
        assert _extract_content_language('<html lang="en">') == "en"

    def test_extracts_html_lang_with_attributes(self) -> None:
        assert (
            _extract_content_language(
                '<html class="no-js" lang="de" dir="ltr">',
            )
            == "de"
        )

    def test_extracts_meta_content_language(self) -> None:
        html = '<meta http-equiv="content-language" content="fr">'
        assert _extract_content_language(html) == "fr"

    def test_html_lang_takes_priority_over_meta(self) -> None:
        html = '<html lang="en"><meta http-equiv="content-language" content="fr">'
        assert _extract_content_language(html) == "en"

    def test_returns_empty_for_no_language(self) -> None:
        assert _extract_content_language("<html><body></body></html>") == ""


# ---------------------------------------------------------------------------
# fetch_aliexpress_part
# ---------------------------------------------------------------------------


class TestFetchAliExpressPart:
    def test_returns_part_on_success(self) -> None:
        with patch(
            "inventree_import_plugin.suppliers.aliexpress.requests.get",
            return_value=_mock_response(_FIXTURE_HTML),
        ):
            part = fetch_aliexpress_part(PRODUCT_ID)

        assert part is not None
        assert part.sku == PRODUCT_ID
        assert part.name == "ESP32 Development Board WiFi+Bluetooth"
        assert part.extra_data["final_url"] == PRODUCT_URL

    def test_final_url_from_redirected_response(self) -> None:
        redirected = "https://www.aliexpress.com/item/1005006274946353.html?spm=redirect"
        with patch(
            "inventree_import_plugin.suppliers.aliexpress.requests.get",
            return_value=_mock_response(_FIXTURE_HTML, url=redirected),
        ):
            part = fetch_aliexpress_part(PRODUCT_ID)

        assert part is not None
        assert part.extra_data["final_url"] == redirected

    def test_returns_none_on_request_exception(self) -> None:
        with patch(
            "inventree_import_plugin.suppliers.aliexpress.requests.get",
            side_effect=_requests.RequestException("timeout"),
        ):
            assert fetch_aliexpress_part(PRODUCT_ID) is None

    def test_returns_none_on_unparseable_page(self) -> None:
        with patch(
            "inventree_import_plugin.suppliers.aliexpress.requests.get",
            return_value=_mock_response("<html><body>nothing</body></html>"),
        ):
            assert fetch_aliexpress_part(PRODUCT_ID) is None

    def test_uses_correct_url(self) -> None:
        with patch(
            "inventree_import_plugin.suppliers.aliexpress.requests.get",
            return_value=_mock_response(_FIXTURE_HTML),
        ) as mock_get:
            fetch_aliexpress_part(PRODUCT_ID)
        mock_get.assert_called_once_with(
            f"https://www.aliexpress.com/item/{PRODUCT_ID}.html",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
        )


# ---------------------------------------------------------------------------
# AliExpressProvider.search_results
# ---------------------------------------------------------------------------


class TestAliExpressProviderSearchResults:
    def setup_method(self) -> None:
        self.provider = AliExpressProvider()
        self.plugin = _mock_plugin()

    def test_returns_single_result_for_url(self) -> None:
        with patch(
            "inventree_import_plugin.providers.aliexpress.fetch_aliexpress_part",
            return_value=_build_part_data(PRODUCT_ID, _FIXTURE_HTML),
        ):
            results = self.provider.search_results(self.plugin, PRODUCT_URL)

        assert len(results) == 1
        assert results[0].sku == PRODUCT_ID
        assert results[0].exact is True
        assert results[0].name == "ESP32 Development Board WiFi+Bluetooth"

    def test_returns_empty_for_keyword(self) -> None:
        results = self.provider.search_results(self.plugin, "ESP32")
        assert results == []

    def test_returns_empty_for_other_domain(self) -> None:
        results = self.provider.search_results(self.plugin, "https://example.com/item/123")
        assert results == []

    def test_returns_empty_on_fetch_failure(self) -> None:
        with patch(
            "inventree_import_plugin.providers.aliexpress.fetch_aliexpress_part",
            return_value=None,
        ):
            results = self.provider.search_results(self.plugin, PRODUCT_URL)
        assert results == []

    def test_returns_empty_on_exception(self) -> None:
        with patch(
            "inventree_import_plugin.providers.aliexpress.fetch_aliexpress_part",
            side_effect=Exception("boom"),
        ):
            results = self.provider.search_results(self.plugin, PRODUCT_URL)
        assert results == []


# ---------------------------------------------------------------------------
# AliExpressProvider.import_data
# ---------------------------------------------------------------------------


class TestAliExpressProviderImportData:
    def setup_method(self) -> None:
        self.provider = AliExpressProvider()
        self.plugin = _mock_plugin()

    def test_returns_part_with_provider_slug(self) -> None:
        with patch(
            "inventree_import_plugin.providers.aliexpress.fetch_aliexpress_part",
            return_value=_build_part_data(PRODUCT_ID, _FIXTURE_HTML),
        ):
            part = self.provider.import_data(self.plugin, PRODUCT_ID)

        assert part is not None
        assert part.extra_data["provider_slug"] == "aliexpress"
        assert part.sku == PRODUCT_ID

    def test_returns_none_on_fetch_failure(self) -> None:
        with patch(
            "inventree_import_plugin.providers.aliexpress.fetch_aliexpress_part",
            return_value=None,
        ):
            assert self.provider.import_data(self.plugin, PRODUCT_ID) is None

    def test_disables_image_when_setting_false(self) -> None:
        plugin = _mock_plugin(ALIEXPRESS_DOWNLOAD_IMAGES=False)
        with patch(
            "inventree_import_plugin.providers.aliexpress.fetch_aliexpress_part",
            return_value=_build_part_data(PRODUCT_ID, _FIXTURE_HTML),
        ):
            part = self.provider.import_data(plugin, PRODUCT_ID)

        assert part is not None
        assert part.image_url == ""

    def test_keeps_image_when_setting_true(self) -> None:
        with patch(
            "inventree_import_plugin.providers.aliexpress.fetch_aliexpress_part",
            return_value=_build_part_data(PRODUCT_ID, _FIXTURE_HTML),
        ):
            part = self.provider.import_data(self.plugin, PRODUCT_ID)

        assert part is not None
        assert part.image_url == "https://ae01.alicdn.com/kf/S123.jpg"


# ---------------------------------------------------------------------------
# SearchResult.id fallback
# ---------------------------------------------------------------------------


class TestSearchResultId:
    def test_id_defaults_to_sku(self) -> None:
        result = SearchResult(sku=PRODUCT_ID, name="ESP32", exact=True)
        assert result.id == PRODUCT_ID

    def test_explicit_id_preserved(self) -> None:
        result = SearchResult(sku=PRODUCT_ID, name="ESP32", exact=True, id="custom")
        assert result.id == "custom"
