"""InvenTree import plugin for Mouser Electronics."""

from __future__ import annotations

import logging
from typing import Any

from inventree_import_plugin import PLUGIN_VERSION
from inventree_import_plugin.base import BaseImportPlugin
from inventree_import_plugin.models import PartData
from inventree_import_plugin.suppliers.mouser import fetch_mouser_part, search_mouser

logger = logging.getLogger(__name__)

try:
    from plugin.mixins import SettingsMixin as _SettingsMixin
except ImportError:

    class _SettingsMixin:  # type: ignore[no-redef]
        """Fallback when InvenTree is not installed."""

        SETTINGS: dict[str, Any] = {}

        def get_setting(self, key: str, default: Any = None) -> Any:
            entry = self.SETTINGS.get(key, {})
            return entry.get("default", default)


class MouserImportPlugin(_SettingsMixin, BaseImportPlugin):  # type: ignore[misc]
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

    def get_suppliers(self) -> list[dict[str, str]]:
        """Return the list of suppliers provided by this plugin."""
        return [
            {
                "name": "Mouser",
                "description": "Mouser Electronics",
                "website": "https://www.mouser.com",
            }
        ]

    def get_search_results(self, supplier_slug: str, term: str) -> list[dict[str, Any]]:
        """Search Mouser for *term* and return a list of candidate parts.

        Args:
            supplier_slug: Supplier identifier (unused; Mouser only serves one supplier).
            term: Search keyword or part number fragment.

        Returns:
            List of dicts with ``supplier_part_number``, ``manufacturer``,
            ``manufacturer_part_number``, and ``description`` keys.
        """
        api_key: str = self.get_setting("MOUSER_API_KEY")
        results = search_mouser(api_key, term)
        return [
            {
                "supplier_part_number": r.sku,
                "manufacturer": r.manufacturer_name,
                "manufacturer_part_number": r.manufacturer_part_number,
                "description": r.description,
            }
            for r in results
        ]

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
