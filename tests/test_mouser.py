"""Tests for Mouser Electronics supplier integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests as _requests

from inventree_import_plugin.base import SearchResult
from inventree_import_plugin.models import PartData, PartParameter, PriceBreak
from inventree_import_plugin.suppliers.mouser import (
    _map_part_data,
    _parse_price,
    _parse_stock,
    fetch_mouser_part,
    search_mouser,
)

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

MOUSER_PART_FIXTURE: dict = {
    "MouserPartNumber": "595-SN74HC595N",
    "ManufacturerPartNumber": "SN74HC595N",
    "Manufacturer": "Texas Instruments",
    "Description": "8-Bit Shift Registers With 3-State Output Registers",
    "DataSheetUrl": "https://www.ti.com/lit/ds/symlink/sn74hc595.pdf",
    "ImagePath": "https://www.mouser.com/images/ti/images/SN74HC595N_t.jpg",
    "LifecycleStatus": "Active",
    "ROHSStatus": "RoHS Compliant",
    "AvailabilityInStock": "12,345 In Stock",
    "PriceBreaks": [
        {"Quantity": 1, "Price": "0.71", "Currency": "USD"},
        {"Quantity": 10, "Price": "0.55", "Currency": "USD"},
        {"Quantity": 100, "Price": "0.35", "Currency": "USD"},
    ],
    "ProductAttributes": [
        {"AttributeName": "Logic Family", "AttributeValue": "HC"},
        {"AttributeName": "Supply Voltage - Min", "AttributeValue": "2 V"},
    ],
    "ProductDetailUrl": "https://www.mouser.com/ProductDetail/595-SN74HC595N",
}


def _mock_response(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.json.return_value = payload
    mock.raise_for_status = MagicMock()
    return mock


# ---------------------------------------------------------------------------
# _parse_stock
# ---------------------------------------------------------------------------


class TestParseStock:
    def test_integer_passthrough(self) -> None:
        assert _parse_stock(100) == 100

    def test_string_with_unit(self) -> None:
        assert _parse_stock("500 In Stock") == 500

    def test_string_with_commas(self) -> None:
        assert _parse_stock("12,345 In Stock") == 12345

    def test_non_numeric_string_returns_zero(self) -> None:
        assert _parse_stock("Non-Stock") == 0

    def test_none_returns_zero(self) -> None:
        assert _parse_stock(None) == 0

    def test_empty_string_returns_zero(self) -> None:
        assert _parse_stock("") == 0


# ---------------------------------------------------------------------------
# _parse_price
# ---------------------------------------------------------------------------


class TestParsePrice:
    def test_plain_decimal(self) -> None:
        assert _parse_price("1.25") == pytest.approx(1.25)

    def test_with_trailing_currency(self) -> None:
        assert _parse_price("0.71 USD") == pytest.approx(0.71)

    def test_comma_as_decimal_separator(self) -> None:
        assert _parse_price("1,25") == pytest.approx(1.25)


# ---------------------------------------------------------------------------
# _map_part_data
# ---------------------------------------------------------------------------


class TestMapPartData:
    def test_basic_fields(self) -> None:
        part = _map_part_data(MOUSER_PART_FIXTURE)
        assert part.sku == "595-SN74HC595N"
        assert part.name == "SN74HC595N"
        assert part.manufacturer_part_number == "SN74HC595N"
        assert part.manufacturer_name == "Texas Instruments"
        assert "Shift Register" in part.description
        assert part.link == "https://www.mouser.com/ProductDetail/595-SN74HC595N"
        assert part.datasheet_url == "https://www.ti.com/lit/ds/symlink/sn74hc595.pdf"

    def test_extra_data_lifecycle_status(self) -> None:
        part = _map_part_data(MOUSER_PART_FIXTURE)
        assert part.extra_data["lifecycle_status"] == "Active"

    def test_rohs_compliant_true(self) -> None:
        part = _map_part_data(MOUSER_PART_FIXTURE)
        assert part.extra_data["rohs_compliant"] is True

    def test_rohs_compliant_false(self) -> None:
        fixture = {**MOUSER_PART_FIXTURE, "ROHSStatus": "Not Compliant"}
        assert _map_part_data(fixture).extra_data["rohs_compliant"] is False

    def test_rohs_missing(self) -> None:
        fixture = {k: v for k, v in MOUSER_PART_FIXTURE.items() if k != "ROHSStatus"}
        assert _map_part_data(fixture).extra_data["rohs_compliant"] is False

    def test_stock_parsed_with_commas(self) -> None:
        assert _map_part_data(MOUSER_PART_FIXTURE).extra_data["stock"] == 12345

    def test_price_breaks_count_and_values(self) -> None:
        part = _map_part_data(MOUSER_PART_FIXTURE)
        assert len(part.price_breaks) == 3
        assert part.price_breaks[0] == PriceBreak(quantity=1, price=0.71, currency="USD")
        assert part.price_breaks[2] == PriceBreak(quantity=100, price=0.35, currency="USD")

    def test_parameters_mapped(self) -> None:
        part = _map_part_data(MOUSER_PART_FIXTURE)
        assert len(part.parameters) == 2
        assert PartParameter(name="Logic Family", value="HC") in part.parameters

    def test_empty_attribute_name_skipped(self) -> None:
        fixture = {
            **MOUSER_PART_FIXTURE,
            "ProductAttributes": [
                {"AttributeName": "", "AttributeValue": "HC"},
                {"AttributeName": "Package", "AttributeValue": "DIP-16"},
            ],
        }
        part = _map_part_data(fixture)
        assert len(part.parameters) == 1
        assert part.parameters[0].name == "Package"

    def test_empty_attribute_value_skipped(self) -> None:
        fixture = {
            **MOUSER_PART_FIXTURE,
            "ProductAttributes": [
                {"AttributeName": "Logic Family", "AttributeValue": ""},
                {"AttributeName": "Package", "AttributeValue": "DIP-16"},
            ],
        }
        assert len(_map_part_data(fixture).parameters) == 1

    def test_missing_fields_use_defaults(self) -> None:
        part = _map_part_data({})
        assert part.sku == ""
        assert part.name == ""
        assert part.manufacturer_name == ""
        assert part.extra_data["stock"] == 0
        assert part.price_breaks == []
        assert part.parameters == []

    def test_returns_part_data_instance(self) -> None:
        assert isinstance(_map_part_data(MOUSER_PART_FIXTURE), PartData)

    def test_packaging_excluded_from_parameters(self) -> None:
        fixture = {
            **MOUSER_PART_FIXTURE,
            "ProductAttributes": [
                {"AttributeName": "Packaging", "AttributeValue": "Tray"},
                {"AttributeName": "Logic Family", "AttributeValue": "HC"},
            ],
        }
        part = _map_part_data(fixture)
        param_names = [p.name for p in part.parameters]
        assert "Packaging" not in param_names
        assert "Logic Family" in param_names

    def test_single_packaging_stored_in_extra_data(self) -> None:
        fixture = {
            **MOUSER_PART_FIXTURE,
            "ProductAttributes": [
                {"AttributeName": "Packaging", "AttributeValue": "Tray"},
            ],
        }
        part = _map_part_data(fixture)
        assert part.extra_data["packaging"] == "Tray"

    def test_duplicate_packaging_combined_with_semicolon(self) -> None:
        fixture = {
            **MOUSER_PART_FIXTURE,
            "ProductAttributes": [
                {"AttributeName": "Packaging", "AttributeValue": "Tray"},
                {"AttributeName": "Packaging", "AttributeValue": "Tape & Reel"},
                {"AttributeName": "Packaging", "AttributeValue": "Cut Tape"},
            ],
        }
        part = _map_part_data(fixture)
        assert part.extra_data["packaging"] == "Tray; Tape & Reel; Cut Tape"
        assert "Packaging" not in [p.name for p in part.parameters]

    def test_no_packaging_omits_key(self) -> None:
        part = _map_part_data(MOUSER_PART_FIXTURE)
        assert "packaging" not in part.extra_data

    def test_empty_packaging_value_skipped(self) -> None:
        fixture = {
            **MOUSER_PART_FIXTURE,
            "ProductAttributes": [
                {"AttributeName": "Packaging", "AttributeValue": ""},
                {"AttributeName": "Packaging", "AttributeValue": "Tray"},
            ],
        }
        part = _map_part_data(fixture)
        assert part.extra_data["packaging"] == "Tray"


# ---------------------------------------------------------------------------
# search_mouser
# ---------------------------------------------------------------------------


class TestSearchMouser:
    def test_returns_parts_on_success(self) -> None:
        response = _mock_response({"Errors": [], "SearchResults": {"Parts": [MOUSER_PART_FIXTURE]}})
        with patch(
            "inventree_import_plugin.suppliers.mouser.requests.post",
            return_value=response,
        ):
            results = search_mouser("test-key", "SN74HC595")

        assert len(results) == 1
        assert results[0].manufacturer_part_number == "SN74HC595N"

    def test_empty_list_on_no_parts(self) -> None:
        response = _mock_response({"Errors": [], "SearchResults": {"Parts": []}})
        with patch(
            "inventree_import_plugin.suppliers.mouser.requests.post",
            return_value=response,
        ):
            assert search_mouser("test-key", "NONEXISTENT") == []

    def test_empty_list_on_api_errors(self) -> None:
        response = _mock_response(
            {"Errors": [{"Message": "Invalid API key"}], "SearchResults": None}
        )
        with patch(
            "inventree_import_plugin.suppliers.mouser.requests.post",
            return_value=response,
        ):
            assert search_mouser("bad-key", "anything") == []

    def test_empty_list_on_request_exception(self) -> None:
        with patch(
            "inventree_import_plugin.suppliers.mouser.requests.post",
            side_effect=_requests.RequestException("timeout"),
        ):
            assert search_mouser("test-key", "SN74HC595") == []

    def test_null_search_results_handled(self) -> None:
        response = _mock_response({"Errors": [], "SearchResults": None})
        with patch(
            "inventree_import_plugin.suppliers.mouser.requests.post",
            return_value=response,
        ):
            assert search_mouser("test-key", "anything") == []


# ---------------------------------------------------------------------------
# fetch_mouser_part
# ---------------------------------------------------------------------------


class TestFetchMouserPart:
    def test_returns_part_on_success(self) -> None:
        response = _mock_response({"Errors": [], "SearchResults": {"Parts": [MOUSER_PART_FIXTURE]}})
        with patch(
            "inventree_import_plugin.suppliers.mouser.requests.post",
            return_value=response,
        ):
            part = fetch_mouser_part("test-key", "595-SN74HC595N")

        assert part is not None
        assert part.sku == "595-SN74HC595N"

    def test_returns_none_when_not_found(self) -> None:
        response = _mock_response({"Errors": [], "SearchResults": {"Parts": []}})
        with patch(
            "inventree_import_plugin.suppliers.mouser.requests.post",
            return_value=response,
        ):
            assert fetch_mouser_part("test-key", "NONEXISTENT") is None

    def test_returns_none_on_api_errors(self) -> None:
        response = _mock_response({"Errors": [{"Message": "API error"}], "SearchResults": None})
        with patch(
            "inventree_import_plugin.suppliers.mouser.requests.post",
            return_value=response,
        ):
            assert fetch_mouser_part("test-key", "595-SN74HC595N") is None

    def test_returns_none_on_request_exception(self) -> None:
        with patch(
            "inventree_import_plugin.suppliers.mouser.requests.post",
            side_effect=_requests.RequestException("connection error"),
        ):
            assert fetch_mouser_part("test-key", "595-SN74HC595N") is None

    def test_returns_first_part_only(self) -> None:
        second = {**MOUSER_PART_FIXTURE, "MouserPartNumber": "OTHER-PN"}
        response = _mock_response(
            {"Errors": [], "SearchResults": {"Parts": [MOUSER_PART_FIXTURE, second]}}
        )
        with patch(
            "inventree_import_plugin.suppliers.mouser.requests.post",
            return_value=response,
        ):
            part = fetch_mouser_part("test-key", "595-SN74HC595N")

        assert part is not None
        assert part.sku == "595-SN74HC595N"


# ---------------------------------------------------------------------------
# SearchResult.id fallback
# ---------------------------------------------------------------------------


class TestSearchResultId:
    """SearchResult.id must always be usable as part_import_id (never null)."""

    def test_search_results_have_id_matching_sku(self) -> None:
        results = [
            SearchResult(
                sku=row.sku,
                name=row.name,
                exact=False,
                description=row.description,
                link=row.link,
                image_url=row.image_url,
            )
            for row in [_map_part_data(MOUSER_PART_FIXTURE)]
        ]
        assert results[0].id == "595-SN74HC595N"

    def test_explicit_id_preserved(self) -> None:
        result = SearchResult(sku="595-SN74HC595N", name="SN74HC595N", exact=False, id="custom")
        assert result.id == "custom"

    def test_empty_string_id_falls_back_to_sku(self) -> None:
        result = SearchResult(sku="595-SN74HC595N", name="SN74HC595N", exact=False, id="")
        assert result.id == "595-SN74HC595N"

    def test_none_id_falls_back_to_sku(self) -> None:
        result = SearchResult(sku="595-SN74HC595N", name="SN74HC595N", exact=False)
        assert result.id == "595-SN74HC595N"
