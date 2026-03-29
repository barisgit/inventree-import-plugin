from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from inventree_import_plugin.compat import SearchResult
from inventree_import_plugin.models import PartData


@dataclass(frozen=True)
class ProviderDefinition:
    slug: str
    name: str
    enabled_setting_key: str
    supplier_setting_key: str
    download_images_setting_key: str
    api_key_setting_key: str | None = None


class ProviderAdapter(Protocol):
    definition: ProviderDefinition

    def search_results(self, plugin: Any, term: str) -> list[SearchResult]: ...

    def import_data(self, plugin: Any, part_id: str) -> PartData | None: ...
