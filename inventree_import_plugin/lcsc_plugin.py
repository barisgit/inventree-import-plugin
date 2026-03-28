"""InvenTree import plugin for LCSC Electronics."""

from __future__ import annotations

import logging
import re
from typing import Any

from inventree_import_plugin import PLUGIN_VERSION
from inventree_import_plugin.base import BaseImportPlugin, SearchResult, Supplier
from inventree_import_plugin.models import PartData
from inventree_import_plugin.suppliers.lcsc import fetch_lcsc_part, search_lcsc

logger = logging.getLogger(__name__)

_LCSC_PART_CODE_RE = re.compile(r"^C\d+$", re.IGNORECASE)


class LCSCImportPlugin(BaseImportPlugin):
    """Import parts from LCSC Electronics into InvenTree.

    Searches the LCSC catalogue and maps results to InvenTree's supplier
    import interface (``get_suppliers`` / ``get_search_results`` /
    ``get_import_data``).
    """

    NAME = "LCSCImportPlugin"
    SLUG = "lcsc-import"
    TITLE = "LCSC Electronics Import"
    DESCRIPTION = "Import parts from LCSC Electronics"
    VERSION = PLUGIN_VERSION

    SETTINGS: dict[str, Any] = {
        "DOWNLOAD_IMAGES": {
            "name": "Download Images",
            "description": "Download part images from LCSC when importing",
            "default": True,
            "validator": bool,
        },
    }

    # ------------------------------------------------------------------
    # UserInterfaceMixin interface
    # ------------------------------------------------------------------

    def get_ui_panels(
        self, request: Any, context: dict[str, Any] | None = None, **kwargs: Any
    ) -> list[dict[str, Any]]:
        """Return a Part-detail panel for enriching from LCSC."""
        if (context or {}).get("target_model") != "part":
            return []
        return [
            {
                "key": "lcsc-enrich",
                "title": "Enrich from LCSC",
                "icon": "ti:refresh:outline",
                "source": self.plugin_static_file("enrich_panel_v2.js:renderEnrichPanel"),
                "context": {"plugin_slug": self.SLUG, "supplier_name": "LCSC"},
            }
        ]

    # ------------------------------------------------------------------
    # SupplierMixin interface
    # ------------------------------------------------------------------

    def get_suppliers(self) -> list[Supplier]:
        """Return the list of suppliers provided by this plugin."""
        return [Supplier(slug="lcsc", name="LCSC")]

    def get_search_results(self, supplier_slug: str, keyword: str) -> list[SearchResult]:
        """Search LCSC for *keyword* and return a list of candidate parts.

        Args:
            supplier_slug: Supplier identifier (unused; LCSC only serves one supplier).
            keyword: Search term (part number or description fragment).

        Returns:
            List of :class:`~plugin.base.supplier.helpers.SearchResult` instances.
        """
        if _LCSC_PART_CODE_RE.match(keyword):
            try:
                part = fetch_lcsc_part(keyword)
            except Exception:
                logger.warning("fetch_lcsc_part failed for product code %s", keyword)
                return []
            results = [
                SearchResult(
                    sku=part.sku,
                    name=part.name,
                    exact=True,
                    description=part.description,
                    link=part.link,
                    image_url=part.image_url,
                )
            ]
            self._annotate_existing_parts(results)
            return results

        raw_results = search_lcsc(keyword)
        results = [
            SearchResult(
                sku=r.get("productCode") or "",
                name=r.get("productModel") or "",
                exact=False,
                description=r.get("productIntroEn") or "",
            )
            for r in raw_results
        ]
        self._annotate_existing_parts(results)
        return results

    def get_import_data(self, supplier_slug: str, supplier_part_number: str) -> PartData:
        """Fetch full part data for *supplier_part_number* from LCSC.

        If the ``DOWNLOAD_IMAGES`` setting is disabled, the image URL is
        cleared so InvenTree will not attempt to download it.

        Args:
            supplier_slug: Supplier identifier (unused; LCSC only serves one supplier).
            supplier_part_number: LCSC part code, e.g. ``C12345``.

        Returns:
            Populated :class:`~inventree_import_plugin.models.PartData`.
        """
        part = fetch_lcsc_part(supplier_part_number)

        if not self.get_setting("DOWNLOAD_IMAGES", True):
            part.image_url = ""

        return part
