"""InvenTree import plugin for Mouser Electronics."""

from __future__ import annotations

import logging
from typing import Any

from inventree_import_plugin import PLUGIN_VERSION
from inventree_import_plugin.base import BaseImportPlugin, SearchResult, Supplier
from inventree_import_plugin.models import PartData
from inventree_import_plugin.suppliers.mouser import fetch_mouser_part, search_mouser

logger = logging.getLogger(__name__)


class MouserImportPlugin(BaseImportPlugin):
    """Import parts from Mouser Electronics into InvenTree.

    Searches the Mouser catalogue via the Mouser Search API and maps results
    to InvenTree's supplier import interface (``get_suppliers`` /
    ``get_search_results`` / ``get_import_data``).
    """

    NAME = "MouserImportPlugin"
    SLUG = "mouser-import"
    TITLE = "Mouser Electronics Import"
    DESCRIPTION = "Import parts from Mouser Electronics via the Mouser Search API"
    VERSION = PLUGIN_VERSION

    SETTINGS: dict[str, Any] = {
        "MOUSER_API_KEY": {
            "name": "Mouser API Key",
            "description": "API key for the Mouser Search API (required)",
            "required": True,
            "protected": True,
        },
        "DOWNLOAD_IMAGES": {
            "name": "Download Images",
            "description": "Download part images from Mouser when importing",
            "default": True,
            "validator": bool,
        },
    }

    # ------------------------------------------------------------------
    # SupplierMixin interface
    # ------------------------------------------------------------------

    def get_suppliers(self) -> list[Supplier]:
        """Return the list of suppliers provided by this plugin."""
        return [Supplier(slug="mouser", name="Mouser")]

    def get_search_results(self, supplier_slug: str, term: str) -> list[SearchResult]:
        """Search Mouser for *term* and return a list of candidate parts.

        Args:
            supplier_slug: Supplier identifier (unused; Mouser only serves one supplier).
            term: Search keyword or part number fragment.

        Returns:
            List of :class:`~plugin.base.supplier.helpers.SearchResult` instances.
        """
        api_key: str = self.get_setting("MOUSER_API_KEY")
        raw = search_mouser(api_key, term)
        results = [
            SearchResult(
                sku=r.sku,
                name=r.name,
                exact=False,
                description=r.description,
                link=r.link,
                image_url=r.image_url,
            )
            for r in raw
        ]
        self._annotate_existing_parts(results)
        return results

    def get_import_data(self, supplier_slug: str, part_id: str) -> PartData | None:
        """Fetch full part data for *part_id* from Mouser.

        If the ``DOWNLOAD_IMAGES`` setting is disabled, the image URL is
        cleared so InvenTree will not attempt to download it.

        Args:
            supplier_slug: Supplier identifier (unused; Mouser only serves one supplier).
            part_id: Mouser part number (SKU), e.g. ``595-SN74HC595N``.

        Returns:
            Populated :class:`~inventree_import_plugin.models.PartData`, or
            ``None`` if the part is not found.
        """
        api_key: str = self.get_setting("MOUSER_API_KEY")
        part = fetch_mouser_part(api_key, part_id)

        if part and not self.get_setting("DOWNLOAD_IMAGES", True):
            part.image_url = ""

        return part
