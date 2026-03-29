from __future__ import annotations

from typing import Any

from inventree_import_plugin.compat import SearchResult
from inventree_import_plugin.models import PartData
from inventree_import_plugin.providers.base import ProviderDefinition
from inventree_import_plugin.suppliers.mouser import fetch_mouser_part, search_mouser

MOUSER_DEFINITION = ProviderDefinition(
    slug="mouser",
    name="Mouser",
    enabled_setting_key="MOUSER_ENABLED",
    supplier_setting_key="MOUSER_SUPPLIER",
    download_images_setting_key="MOUSER_DOWNLOAD_IMAGES",
    api_key_setting_key="MOUSER_API_KEY",
)


class MouserProvider:
    definition = MOUSER_DEFINITION

    def search_results(self, plugin: Any, term: str) -> list[SearchResult]:
        api_key = str(plugin.get_setting("MOUSER_API_KEY", "") or "")
        raw_results = search_mouser(api_key, term)

        return [
            SearchResult(
                sku=row.sku,
                name=row.name,
                exact=False,
                description=row.description,
                link=row.link,
                image_url=row.image_url,
            )
            for row in raw_results
        ]

    def import_data(self, plugin: Any, part_id: str) -> PartData | None:
        api_key = str(plugin.get_setting("MOUSER_API_KEY", "") or "")
        part = fetch_mouser_part(api_key, part_id)

        if part and not plugin.get_setting(self.definition.download_images_setting_key, True):
            part.image_url = ""

        if part:
            part.extra_data["provider_slug"] = self.definition.slug

        return part
