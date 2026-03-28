from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict


@dataclass
class PriceBreak:
    quantity: int
    price: float
    currency: str = "EUR"


@dataclass
class PartParameter:
    name: str
    value: str
    units: str = ""


@dataclass
class PartData:
    # Identification
    sku: str
    name: str
    description: str

    # Manufacturer info
    manufacturer_name: str = ""
    manufacturer_part_number: str = ""

    # Links and media
    link: str = ""
    image_url: str = ""
    datasheet_url: str = ""

    # Structured data
    price_breaks: list[PriceBreak] = field(default_factory=list)
    parameters: list[PartParameter] = field(default_factory=list)

    # Extra supplier-specific data
    extra_data: dict = field(default_factory=dict)  # type: ignore[type-arg]


class Supplier(TypedDict):
    """Supplier entry returned by ``get_suppliers()``."""

    name: str
    description: str
    website: str


class SearchResult(TypedDict):
    """Search result entry returned by ``get_search_results()``."""

    supplier_part_number: str
    manufacturer: str
    manufacturer_part_number: str
    description: str
