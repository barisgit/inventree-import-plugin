"""AliExpress HTML-only supplier client — no internal API, no BeautifulSoup."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from inventree_import_plugin.models import PartData, PartParameter, PriceBreak

logger = logging.getLogger(__name__)

_ALIEXPRESS_ITEM_URL_RE = re.compile(
    r"(?:https?://)?(?:[\w-]+\.)?aliexpress\.(?:com|us)/item/(?:[\w-]+/)?(\d+)",
    re.IGNORECASE,
)

_META_OG_RE = re.compile(
    r"<meta\s+[^>]*property=[\"']og:(\w+)[\"'][^>]*>",
    re.IGNORECASE,
)
_CONTENT_ATTR_RE = re.compile(r'content=["\']([^"\']*)["\']', re.IGNORECASE)

_DC_DATA_CALL_MARKER = "window._d_c_.DCData("
_DC_DATA_ASSIGN_MARKER = "window._d_c_.DCData = "
_BOOTSTRAP_MARKER = "window.runParams = "

_REQUEST_TIMEOUT = 15
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def extract_product_id(term: str) -> str | None:
    """Extract AliExpress product ID from a URL string.

    Returns ``None`` for non-AliExpress input (keyword searches, other domains).
    """
    match = _ALIEXPRESS_ITEM_URL_RE.search(term)
    return match.group(1) if match else None


def _parse_meta_tags(html: str) -> dict[str, str]:
    """Extract ``og:*`` meta tag key-value pairs from HTML.

    Handles either attribute order (``property`` before/after ``content``).
    """
    result: dict[str, str] = {}
    for match in _META_OG_RE.finditer(html):
        prop = match.group(1)
        content_match = _CONTENT_ATTR_RE.search(match.group(0))
        if content_match:
            result[prop] = content_match.group(1)
    return result


def _extract_json_object(html: str, marker: str) -> dict[str, Any] | None:
    """Find a JSON object in *html* starting after *marker* and decode it."""
    pos = html.find(marker)
    if pos == -1:
        return None
    json_start = pos + len(marker)
    try:
        obj, _ = json.JSONDecoder().raw_decode(html, json_start)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _parse_embedded_data(html: str) -> dict[str, Any]:
    """Try to extract embedded product data from script tags.

    Attempts known markers in priority order and returns the first successful
    parse, or an empty dict.
    """
    for marker in (_DC_DATA_CALL_MARKER, _DC_DATA_ASSIGN_MARKER, _BOOTSTRAP_MARKER):
        data = _extract_json_object(html, marker)
        if data:
            return data
    return {}


def _parse_price_breaks(data: dict[str, Any]) -> list[PriceBreak]:
    """Extract price breaks from embedded ``priceModule``."""
    price_module = data.get("priceModule") or {}
    if not price_module:
        return []

    currency = price_module.get("currency", "USD")

    # Tiered pricing
    prices = price_module.get("prices") or []
    if prices:
        result: list[PriceBreak] = []
        for tier in prices:
            qty = tier.get("min") or tier.get("quantity")
            price = tier.get("price")
            if qty is not None and price is not None:
                try:
                    result.append(
                        PriceBreak(
                            quantity=int(qty),
                            price=float(str(price).replace(",", ".")),
                            currency=currency,
                        )
                    )
                except (ValueError, TypeError):
                    continue
        return result

    # Single-price fallback
    min_amount = price_module.get("minAmount")
    if min_amount is not None:
        try:
            return [
                PriceBreak(
                    quantity=1,
                    price=float(str(min_amount).replace(",", ".")),
                    currency=currency,
                )
            ]
        except (ValueError, TypeError):
            pass

    return []


def _parse_parameters(data: dict[str, Any]) -> list[PartParameter]:
    """Extract parameters from embedded ``specsModule``."""
    specs_module = data.get("specsModule") or {}
    props = specs_module.get("props") or []
    result: list[PartParameter] = []
    for prop in props:
        name = prop.get("attrName", "")
        value = prop.get("attrValue", "")
        if name and value:
            result.append(PartParameter(name=name, value=value))
    return result


def _parse_stock(data: dict[str, Any]) -> int | None:
    """Extract stock count from embedded ``quantityModule``."""
    qty_module = data.get("quantityModule") or {}
    total = qty_module.get("totalAvail")
    if total is not None:
        try:
            return int(total)
        except (ValueError, TypeError):
            pass
    return None


def _build_part_data(product_id: str, html: str) -> PartData | None:
    """Build a :class:`PartData` from raw AliExpress HTML.

    Returns ``None`` when essential data (product title) cannot be extracted.
    """
    meta = _parse_meta_tags(html)
    embedded = _parse_embedded_data(html)

    name = meta.get("title", "")
    if not name:
        return None

    description = meta.get("description", "")
    image_url = meta.get("image", "")
    link = f"https://www.aliexpress.com/item/{product_id}.html"

    price_breaks = _parse_price_breaks(embedded)
    parameters = _parse_parameters(embedded)
    stock = _parse_stock(embedded)

    extra_data: dict[str, Any] = {}
    if stock is not None:
        extra_data["stock"] = stock

    return PartData(
        sku=product_id,
        name=name,
        description=description,
        manufacturer_name="",
        manufacturer_part_number="",
        link=link,
        image_url=image_url,
        price_breaks=price_breaks,
        parameters=parameters,
        extra_data=extra_data,
    )


def fetch_aliexpress_part(product_id: str) -> PartData | None:
    """Fetch an AliExpress product page by *product_id* and return a :class:`PartData`.

    Uses HTML scraping only — no internal API calls, no BeautifulSoup.
    Returns ``None`` on network errors or when the page cannot be parsed.
    """
    url = f"https://www.aliexpress.com/item/{product_id}.html"
    try:
        response = requests.get(url, headers=_REQUEST_HEADERS, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("AliExpress fetch failed for product %s: %s", product_id, exc)
        return None

    return _build_part_data(product_id, response.text)
