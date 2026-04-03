"""Mouser Electronics supplier API client."""

from __future__ import annotations

import logging
from typing import Any

import requests

from inventree_import_plugin import PLUGIN_VERSION  # noqa: F401 — re-exported for plugin metadata
from inventree_import_plugin.models import PartData, PartParameter, PriceBreak

logger = logging.getLogger(__name__)

MOUSER_API_BASE = "https://api.mouser.com/api/v1"
MOUSER_SEARCH_KEYWORD_URL = f"{MOUSER_API_BASE}/search/keyword"
MOUSER_SEARCH_PARTNUMBER_URL = f"{MOUSER_API_BASE}/search/partnumber"

_REQUEST_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}
_REQUEST_TIMEOUT = 30


def _parse_stock(availability: Any) -> int:
    """Parse a Mouser availability value to an integer stock count."""
    if isinstance(availability, int):
        return availability
    if isinstance(availability, str):
        try:
            return int(availability.split()[0].replace(",", ""))
        except (ValueError, IndexError):
            return 0
    return 0


def _parse_price(price_str: str) -> float:
    """Parse a Mouser price string (e.g. '0.71' or '1,25 USD') to float."""
    try:
        return float(str(price_str).split()[0].replace(",", "."))
    except (ValueError, IndexError):
        return 0.0


def _map_part_data(part: dict[str, Any]) -> PartData:
    """Map a Mouser API part dict to a normalised :class:`PartData` instance."""
    packaging_values: list[str] = []
    parameters: list[PartParameter] = []
    for attr in part.get("ProductAttributes", []):
        name = attr.get("AttributeName", "")
        value = attr.get("AttributeValue", "")
        if not name or not value:
            continue
        if name == "Packaging":
            packaging_values.append(value)
            continue
        parameters.append(PartParameter(name=name, value=value))

    price_breaks: list[PriceBreak] = []
    for pb in part.get("PriceBreaks", []):
        qty = pb.get("Quantity")
        price_str = pb.get("Price")
        currency = pb.get("Currency", "USD")
        if qty is not None and price_str:
            price_breaks.append(
                PriceBreak(
                    quantity=int(qty),
                    price=_parse_price(price_str),
                    currency=currency,
                )
            )

    rohs_status = part.get("ROHSStatus", "")
    rohs_lower = rohs_status.lower() if rohs_status else ""
    # True when Mouser reports "RoHS Compliant" or "ROHS3 Compliant" etc.
    # Excludes "Not Compliant" by requiring the string to begin with "rohs".
    rohs_compliant = rohs_lower.startswith("rohs") and "compliant" in rohs_lower

    availability = part.get("AvailabilityInStock") or part.get("Availability", 0)
    manufacturer_part_number = part.get("ManufacturerPartNumber", "")

    return PartData(
        sku=part.get("MouserPartNumber", ""),
        name=manufacturer_part_number,
        manufacturer_part_number=manufacturer_part_number,
        manufacturer_name=part.get("Manufacturer", ""),
        description=part.get("Description", ""),
        link=part.get("ProductDetailUrl", ""),
        datasheet_url=part.get("DataSheetUrl", ""),
        image_url=part.get("ImagePath", ""),
        parameters=parameters,
        price_breaks=price_breaks,
        extra_data={
            "lifecycle_status": part.get("LifecycleStatus", ""),
            "rohs_compliant": rohs_compliant,
            "stock": _parse_stock(availability),
            **({"packaging": "; ".join(packaging_values)} if packaging_values else {}),
        },
    )


def search_mouser(api_key: str, term: str) -> list[PartData]:
    """Search Mouser Electronics by keyword.

    POSTs to the Mouser keyword search endpoint and maps results to
    :class:`~inventree_import_plugin.models.PartData` instances.

    Args:
        api_key: Mouser API key.
        term: Search keyword or part number fragment.

    Returns:
        List of matching :class:`PartData` instances; empty list on error or
        when no results are found.
    """
    payload = {
        "SearchByKeywordRequest": {
            "keyword": term,
            "records": 25,
            "startingRecord": 0,
            "searchOptions": "None",
            "searchWithYourSignUpLanguage": "false",
        }
    }
    try:
        response = requests.post(
            MOUSER_SEARCH_KEYWORD_URL,
            params={"apiKey": api_key},
            json=payload,
            headers=_REQUEST_HEADERS,
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logger.error("Mouser keyword search failed for %r: %s", term, exc)
        return []

    errors = data.get("Errors") or []
    if errors:
        logger.error("Mouser API errors for search %r: %s", term, errors)
        return []

    parts = (data.get("SearchResults") or {}).get("Parts") or []
    return [_map_part_data(p) for p in parts]


def fetch_mouser_part(api_key: str, sku: str) -> PartData | None:
    """Fetch a single Mouser part by Mouser part number (SKU).

    POSTs an exact part-number search to the Mouser Search API.

    Args:
        api_key: Mouser API key.
        sku: Mouser part number (SKU).

    Returns:
        :class:`PartData` for the matched part, or ``None`` if not found or on
        error.
    """
    payload = {
        "SearchByPartRequest": {
            "mouserPartNumber": sku,
            "partSearchOptions": "Exact",
        }
    }
    try:
        response = requests.post(
            MOUSER_SEARCH_PARTNUMBER_URL,
            params={"apiKey": api_key},
            json=payload,
            headers=_REQUEST_HEADERS,
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logger.error("Mouser part fetch failed for SKU %r: %s", sku, exc)
        return None

    errors = data.get("Errors") or []
    if errors:
        logger.error("Mouser API errors for SKU %r: %s", sku, errors)
        return None

    parts = (data.get("SearchResults") or {}).get("Parts") or []
    if not parts:
        logger.warning("No Mouser part found for SKU %r", sku)
        return None

    return _map_part_data(parts[0])
