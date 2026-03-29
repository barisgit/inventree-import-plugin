from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Supplier:
    slug: str
    name: str


@dataclass
class SearchResult:
    sku: str
    name: str
    exact: bool
    description: str | None = None
    price: str | None = None
    link: str | None = None
    image_url: str | None = None
    id: str | None = None
    existing_part: Any | None = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = self.sku


__all__ = ["SearchResult", "Supplier"]
