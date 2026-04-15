from __future__ import annotations

import logging
from typing import Any

from inventree_import_plugin.compat import SearchResult
from inventree_import_plugin.models import PartData
from inventree_import_plugin.providers.base import ProviderDefinition
from inventree_import_plugin.suppliers.aliexpress import (
    extract_product_id,
    fetch_aliexpress_part,
)

logger = logging.getLogger(__name__)

ALIEXPRESS_DEFINITION = ProviderDefinition(
    slug="aliexpress",
    name="AliExpress",
    enabled_setting_key="ALIEXPRESS_ENABLED",
    supplier_setting_key="ALIEXPRESS_SUPPLIER",
    download_images_setting_key="ALIEXPRESS_DOWNLOAD_IMAGES",
)


class AliExpressProvider:
    definition = ALIEXPRESS_DEFINITION

    def search_results(self, plugin: Any, term: str) -> list[SearchResult]:
        """Accept an AliExpress item URL, return one exact SearchResult.

        Returns an empty list for non-AliExpress input or parse failures.
        """
        product_id = extract_product_id(term)
        if not product_id:
            return []

        try:
            part = fetch_aliexpress_part(product_id)
        except Exception:
            logger.warning("fetch_aliexpress_part failed for product %s", product_id)
            return []

        if not part:
            return []

        return [
            SearchResult(
                sku=part.sku,
                name=part.name,
                exact=True,
                description=part.description,
                link=part.link,
                image_url=part.image_url,
            )
        ]

    def import_data(self, plugin: Any, part_id: str) -> PartData | None:
        """Fetch PartData for an AliExpress product; disable image if setting says so."""
        part = fetch_aliexpress_part(part_id)

        if not part:
            return None

        if not plugin.get_setting(self.definition.download_images_setting_key, True):
            part.image_url = ""

        part.extra_data["provider_slug"] = self.definition.slug
        return part
