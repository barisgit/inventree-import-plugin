from __future__ import annotations

import logging
import re
from typing import Any

from inventree_import_plugin.compat import SearchResult
from inventree_import_plugin.models import PartData
from inventree_import_plugin.providers.base import ProviderDefinition
from inventree_import_plugin.suppliers.lcsc import fetch_lcsc_part, search_lcsc

logger = logging.getLogger(__name__)

_LCSC_PART_CODE_RE = re.compile(r"^C\d+$", re.IGNORECASE)

LCSC_DEFINITION = ProviderDefinition(
    slug="lcsc",
    name="LCSC",
    enabled_setting_key="LCSC_ENABLED",
    supplier_setting_key="LCSC_SUPPLIER",
    download_images_setting_key="LCSC_DOWNLOAD_IMAGES",
)


class LCSCProvider:
    definition = LCSC_DEFINITION

    def search_results(self, plugin: Any, term: str) -> list[SearchResult]:
        if _LCSC_PART_CODE_RE.match(term):
            try:
                part = fetch_lcsc_part(term)
            except Exception:
                logger.warning("fetch_lcsc_part failed for product code %s", term)
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

        raw_results = search_lcsc(term)
        return [
            SearchResult(
                sku=row.get("productCode") or "",
                name=row.get("productModel") or "",
                exact=False,
                description=row.get("productIntroEn") or "",
            )
            for row in raw_results
        ]

    def import_data(self, plugin: Any, part_id: str) -> PartData:
        part = fetch_lcsc_part(part_id)

        if not plugin.get_setting(self.definition.download_images_setting_key, True):
            part.image_url = ""

        part.extra_data["provider_slug"] = self.definition.slug
        return part
