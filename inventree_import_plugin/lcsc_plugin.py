"""InvenTree import plugin for LCSC Electronics."""

from __future__ import annotations

import logging
from typing import Any

from inventree_import_plugin import PLUGIN_VERSION
from inventree_import_plugin.base import BaseImportPlugin
from inventree_import_plugin.models import PartData
from inventree_import_plugin.suppliers.lcsc import fetch_lcsc_part, search_lcsc

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


class LCSCImportPlugin(_SettingsMixin, BaseImportPlugin):  # type: ignore[misc]
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
    # SupplierMixin interface
    # ------------------------------------------------------------------

    def get_suppliers(self) -> list[dict[str, str]]:
        """Return the list of suppliers provided by this plugin."""
        return [
            {
                "name": "LCSC",
                "description": "LCSC Electronics",
                "website": "https://lcsc.com",
            }
        ]

    def get_search_results(self, keyword: str) -> list[dict[str, Any]]:
        """Search LCSC for *keyword* and return a list of candidate parts.

        Each dict contains the fields needed by InvenTree to display search
        results before the user picks one to import.

        Args:
            keyword: Search term (part number or description fragment).

        Returns:
            List of dicts with ``supplier_part_number``, ``manufacturer``,
            ``manufacturer_part_number``, and ``description`` keys.
        """
        raw_results = search_lcsc(keyword)
        return [
            {
                "supplier_part_number": r.get("productCode") or "",
                "manufacturer": r.get("brandNameEn") or "",
                "manufacturer_part_number": r.get("productModel") or "",
                "description": r.get("productIntroEn") or "",
            }
            for r in raw_results
        ]

    def get_import_data(self, supplier_part_number: str) -> PartData:
        """Fetch full part data for *supplier_part_number* from LCSC.

        If the ``DOWNLOAD_IMAGES`` setting is disabled, the image URL is
        cleared so InvenTree will not attempt to download it.

        Args:
            supplier_part_number: LCSC part code, e.g. ``C12345``.

        Returns:
            Populated :class:`~inventree_import_plugin.models.PartData`.
        """
        part = fetch_lcsc_part(supplier_part_number)

        if not self.get_setting("DOWNLOAD_IMAGES", True):
            part.image_url = ""

        return part
