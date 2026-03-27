"""Tests for the LCSC API client (suppliers/lcsc.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from inventree_import_plugin.models import PartData, PartParameter, PriceBreak
from inventree_import_plugin.suppliers.lcsc import (
    _map_to_part_data,
    _parse_parameters,
    _parse_price_breaks,
    fetch_lcsc_part,
    search_lcsc,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_PRODUCT: dict = {
    "productCode": "C12345",
    "productModel": "LM358",
    "brandNameEn": "Texas Instruments",
    "productIntroEn": "Dual op-amp",
    "pdfUrl": "https://example.com/ds.pdf",
    "productImages": ["https://example.com/img.jpg"],
    "productPriceList": [
        {"ladder": "1", "productPrice": "0.15"},
        {"ladder": "10", "productPrice": "0.12"},
    ],
    "paramVOList": [
        {"paramNameEn": "Supply Voltage", "paramValueEn": "3.3V"},
        {"paramNameEn": "Channels", "paramValueEn": "-"},  # should be skipped
    ],
}


# ---------------------------------------------------------------------------
# _map_to_part_data
# ---------------------------------------------------------------------------


class TestMapToPartData:
    def test_basic_mapping(self) -> None:
        part = _map_to_part_data(MINIMAL_PRODUCT)
        assert part.sku == "C12345"
        assert part.name == "LM358"
        assert part.description == "Dual op-amp"
        assert part.manufacturer_name == "Texas Instruments"
        assert part.manufacturer_part_number == "LM358"
        assert part.datasheet_url == "https://example.com/ds.pdf"
        assert part.image_url == "https://example.com/img.jpg"
        assert part.link == "https://lcsc.com/product-detail/C12345.html"

    def test_name_falls_back_to_sku_when_no_model(self) -> None:
        product = {**MINIMAL_PRODUCT, "productModel": None}
        part = _map_to_part_data(product)
        assert part.name == "C12345"

    def test_image_url_falls_back_to_single_field(self) -> None:
        product = {**MINIMAL_PRODUCT, "productImages": None, "productImageUrl": "https://img2.com/x.jpg"}
        part = _map_to_part_data(product)
        assert part.image_url == "https://img2.com/x.jpg"

    def test_image_url_empty_when_none_available(self) -> None:
        product = {**MINIMAL_PRODUCT, "productImages": None, "productImageUrl": None}
        part = _map_to_part_data(product)
        assert part.image_url == ""

    def test_empty_sku_produces_empty_link(self) -> None:
        product = {**MINIMAL_PRODUCT, "productCode": None}
        part = _map_to_part_data(product)
        assert part.link == ""

    def test_price_breaks_parsed(self) -> None:
        part = _map_to_part_data(MINIMAL_PRODUCT)
        assert len(part.price_breaks) == 2
        assert part.price_breaks[0] == PriceBreak(quantity=1, price=0.15, currency="EUR")
        assert part.price_breaks[1] == PriceBreak(quantity=10, price=0.12, currency="EUR")

    def test_dash_parameter_skipped(self) -> None:
        part = _map_to_part_data(MINIMAL_PRODUCT)
        names = [p.name for p in part.parameters]
        assert "Supply Voltage" in names
        assert "Channels" not in names

    def test_returns_part_data_instance(self) -> None:
        part = _map_to_part_data(MINIMAL_PRODUCT)
        assert isinstance(part, PartData)


# ---------------------------------------------------------------------------
# _parse_price_breaks
# ---------------------------------------------------------------------------


class TestParsePriceBreaks:
    def test_comma_decimal_separator(self) -> None:
        product = {"productPriceList": [{"ladder": "5", "productPrice": "1,25"}]}
        breaks = _parse_price_breaks(product, "C1")
        assert breaks == [PriceBreak(quantity=5, price=1.25, currency="EUR")]

    def test_float_price(self) -> None:
        product = {"productPriceList": [{"ladder": "1", "productPrice": 0.99}]}
        breaks = _parse_price_breaks(product, "C1")
        assert breaks[0].price == pytest.approx(0.99)

    def test_bad_entry_skipped(self) -> None:
        product = {"productPriceList": [{"ladder": "bad", "productPrice": "1.00"}]}
        breaks = _parse_price_breaks(product, "C1")
        assert breaks == []

    def test_missing_price_list(self) -> None:
        assert _parse_price_breaks({}, "C1") == []


# ---------------------------------------------------------------------------
# _parse_parameters
# ---------------------------------------------------------------------------


class TestParseParameters:
    def test_valid_parameter(self) -> None:
        product = {
            "paramVOList": [{"paramNameEn": "Voltage", "paramValueEn": "3.3V"}]
        }
        params = _parse_parameters(product, "C1")
        assert params == [PartParameter(name="Voltage", value="3.3V")]

    def test_dash_value_skipped(self) -> None:
        product = {
            "paramVOList": [{"paramNameEn": "Pkg", "paramValueEn": "-"}]
        }
        assert _parse_parameters(product, "C1") == []

    def test_missing_param_list(self) -> None:
        assert _parse_parameters({}, "C1") == []


# ---------------------------------------------------------------------------
# search_lcsc
# ---------------------------------------------------------------------------


class TestSearchLcsc:
    def _mock_response(self, product_list: list) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {
            "result": {
                "productSearchResultVO": {
                    "productList": product_list
                }
            }
        }
        resp.raise_for_status.return_value = None
        return resp

    def test_returns_product_list(self) -> None:
        products = [{"productCode": "C1"}, {"productCode": "C2"}]
        with patch("inventree_import_plugin.suppliers.lcsc.requests.post") as mock_post:
            mock_post.return_value = self._mock_response(products)
            result = search_lcsc("LM358")
        assert result == products

    def test_posts_to_correct_url(self) -> None:
        with patch("inventree_import_plugin.suppliers.lcsc.requests.post") as mock_post:
            mock_post.return_value = self._mock_response([])
            search_lcsc("test")
        call_args = mock_post.call_args
        assert "search/v2/global" in call_args[0][0]
        assert call_args[1]["json"] == {"keyword": "test"}

    def test_empty_result_returns_empty_list(self) -> None:
        with patch("inventree_import_plugin.suppliers.lcsc.requests.post") as mock_post:
            resp = MagicMock()
            resp.json.return_value = {"result": {}}
            resp.raise_for_status.return_value = None
            mock_post.return_value = resp
            result = search_lcsc("unknown")
        assert result == []

    def test_http_error_propagates(self) -> None:
        with patch("inventree_import_plugin.suppliers.lcsc.requests.post") as mock_post:
            mock_post.return_value.raise_for_status.side_effect = requests.HTTPError("404")
            with pytest.raises(requests.HTTPError):
                search_lcsc("test")


# ---------------------------------------------------------------------------
# fetch_lcsc_part
# ---------------------------------------------------------------------------


class TestFetchLcscPart:
    def _mock_response(self, product: dict | None) -> MagicMock:
        resp = MagicMock()
        resp.json.return_value = {"result": product}
        resp.raise_for_status.return_value = None
        return resp

    def test_returns_part_data(self) -> None:
        with patch("inventree_import_plugin.suppliers.lcsc.requests.get") as mock_get:
            mock_get.return_value = self._mock_response(MINIMAL_PRODUCT)
            part = fetch_lcsc_part("C12345")
        assert isinstance(part, PartData)
        assert part.sku == "C12345"

    def test_gets_correct_url_and_param(self) -> None:
        with patch("inventree_import_plugin.suppliers.lcsc.requests.get") as mock_get:
            mock_get.return_value = self._mock_response(MINIMAL_PRODUCT)
            fetch_lcsc_part("C12345")
        call_args = mock_get.call_args
        assert "product/detail" in call_args[0][0]
        assert call_args[1]["params"] == {"productCode": "C12345"}

    def test_raises_value_error_on_empty_result(self) -> None:
        with patch("inventree_import_plugin.suppliers.lcsc.requests.get") as mock_get:
            mock_get.return_value = self._mock_response(None)
            with pytest.raises(ValueError, match="No result"):
                fetch_lcsc_part("C99999")

    def test_http_error_propagates(self) -> None:
        with patch("inventree_import_plugin.suppliers.lcsc.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.side_effect = requests.HTTPError("500")
            with pytest.raises(requests.HTTPError):
                fetch_lcsc_part("C12345")
