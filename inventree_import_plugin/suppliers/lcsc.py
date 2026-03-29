"""LCSC Electronics API client.

Provides two public functions:
- search_lcsc(term)         -- keyword search via POST
- fetch_lcsc_part(code)     -- full part detail via GET

No authentication is required. A browser-like User-Agent and EUR currency
cookie are set to match normal browser behaviour.  Price-break parsing reads
the ``currencyCode`` / ``currencyPrice`` fields from the API response so the
correct numeric amount and currency label are used regardless of which
currency the cookie requests.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from inventree_import_plugin.models import PartData, PartParameter, PriceBreak

logger = logging.getLogger(__name__)

_BASE_URL = "https://wmsc.lcsc.com/ftps/wm"
_SEARCH_URL = f"{_BASE_URL}/search/v2/global"
_DETAIL_URL = f"{_BASE_URL}/product/detail"

_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cookie": "currencyCode=EUR",
}

_REQUEST_TIMEOUT = 15


def search_lcsc(term: str) -> list[dict[str, Any]]:
    """Search LCSC for parts matching *term*.

    Args:
        term: Keyword or part number to search for.

    Returns:
        Raw list of product dicts from the LCSC search API.
        Empty list if the query returns no results.

    Raises:
        requests.HTTPError: On a non-2xx HTTP status.
        requests.RequestException: On any other network error.
    """
    response = requests.post(
        _SEARCH_URL,
        json={"keyword": term},
        headers=_HEADERS,
        timeout=_REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    data: dict[str, Any] = response.json()
    result = data.get("result") or {}
    product_search = result.get("productSearchResultVO") or {}
    return product_search.get("productList") or []


def fetch_lcsc_part(product_code: str) -> PartData:
    """Fetch full part details from LCSC and return a normalised PartData.

    Args:
        product_code: LCSC part number, e.g. ``C12345``.

    Returns:
        Populated :class:`~inventree_import_plugin.models.PartData`.

    Raises:
        requests.HTTPError: On a non-2xx HTTP status.
        requests.RequestException: On any other network error.
        ValueError: If the API response is missing the ``result`` key.
    """
    response = requests.get(
        _DETAIL_URL,
        params={"productCode": product_code},
        headers=_HEADERS,
        timeout=_REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    data: dict[str, Any] = response.json()
    product = data.get("result")
    if not product:
        raise ValueError(f"No result in LCSC response for {product_code!r}")

    return _map_to_part_data(product)


def _map_to_part_data(product: dict[str, Any]) -> PartData:
    """Map a raw LCSC product dict to a :class:`PartData` instance."""
    sku = product.get("productCode") or ""
    name = product.get("productModel") or sku
    description = product.get("productIntroEn") or ""
    manufacturer_name = product.get("brandNameEn") or ""
    manufacturer_part_number = product.get("productModel") or ""
    datasheet_url = product.get("pdfUrl") or ""

    # productImages is a list; fall back to single productImageUrl
    images = product.get("productImages")
    if isinstance(images, list) and images:
        image_url = str(images[0])
    else:
        image_url = str(product.get("productImageUrl") or "")

    link = f"https://lcsc.com/product-detail/{sku}.html" if sku else ""

    price_breaks = _parse_price_breaks(product, sku)
    parameters = _parse_parameters(product, sku)

    return PartData(
        sku=sku,
        name=name,
        description=description,
        manufacturer_name=manufacturer_name,
        manufacturer_part_number=manufacturer_part_number,
        link=link,
        image_url=image_url,
        datasheet_url=datasheet_url,
        price_breaks=price_breaks,
        parameters=parameters,
    )


def _parse_price_breaks(product: dict[str, Any], sku: str) -> list[PriceBreak]:
    """Extract price breaks using the supplier-provided currency.

    LCSC returns ``productPrice`` (always USD-base) and optionally
    ``currencyPrice`` (converted to the currency requested via cookie).
    Each entry (or the product root) carries ``currencyCode`` indicating
    which currency ``currencyPrice`` is expressed in.

    When ``currencyCode`` is present and not USD we prefer ``currencyPrice``;
    otherwise we fall back to ``productPrice`` and label it USD.
    """
    breaks: list[PriceBreak] = []
    product_currency = (product.get("currencyCode") or "").upper()

    for entry in product.get("productPriceList") or []:
        try:
            qty = int(entry["ladder"])
            entry_currency = (entry.get("currencyCode") or product_currency or "USD").upper()

            # currencyPrice is the amount converted to the requested currency;
            # productPrice is always the USD base price.
            if entry_currency != "USD" and "currencyPrice" in entry:
                raw_price = entry["currencyPrice"]
            else:
                raw_price = entry["productPrice"]
                entry_currency = entry_currency or "USD"

            if isinstance(raw_price, str):
                price = float(raw_price.replace(",", "."))
            else:
                price = float(raw_price)

            breaks.append(PriceBreak(quantity=qty, price=price, currency=entry_currency))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping unparseable price entry for %s: %s (%s)", sku, entry, exc)
    return breaks


def _parse_parameters(product: dict[str, Any], sku: str) -> list[PartParameter]:
    params: list[PartParameter] = []
    for param in product.get("paramVOList") or []:
        name = param.get("paramNameEn") or ""
        value = param.get("paramValueEn") or ""
        if name and value and value.strip() != "-":
            params.append(PartParameter(name=name, value=value))
    return params
