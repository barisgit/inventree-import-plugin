from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from inventree_import_plugin import PLUGIN_VERSION
from inventree_import_plugin.models import PartData

__all__ = ["BaseImportPlugin", "SearchResult", "Supplier"]

logger = logging.getLogger("inventree_import_plugin")


class _FallbackBase:
    """Stub used when InvenTree is not installed."""


class _FallbackMixin:
    """Stub used when InvenTree is not installed."""


try:
    from plugin import InvenTreePlugin as _InvenTreePlugin
    from plugin.mixins import SupplierMixin as _SupplierMixin

    _INVENTREE_AVAILABLE = True
except ImportError:
    _InvenTreePlugin = _FallbackBase
    _SupplierMixin = _FallbackMixin
    _INVENTREE_AVAILABLE = False


try:
    from plugin.base.supplier.helpers import SearchResult, Supplier
except ImportError:

    @dataclass
    class Supplier:  # type: ignore[no-redef]
        slug: str
        name: str

    @dataclass
    class SearchResult:  # type: ignore[no-redef]
        sku: str
        name: str
        exact: bool
        description: str | None = None
        price: str | None = None
        link: str | None = None
        image_url: str | None = None
        id: str | None = None
        existing_part: Any | None = None


class BaseImportPlugin(_SupplierMixin, _InvenTreePlugin):  # type: ignore[misc]
    VERSION = PLUGIN_VERSION

    def _annotate_existing_parts(self, results: list[SearchResult]) -> None:
        """Set existing_part on each result where a matching SupplierPart already exists."""
        if not _INVENTREE_AVAILABLE:
            return
        from company.models import SupplierPart

        for result in results:
            supplier_part = (
                SupplierPart.objects.filter(
                    supplier=self.supplier_company, SKU=result.sku
                )
                .select_related("part")
                .first()
            )
            if supplier_part is not None:
                result.existing_part = supplier_part.part

    def get_pricing_data(self, data: PartData) -> dict[int, tuple[float, str]]:
        return {pb.quantity: (pb.price, pb.currency) for pb in data.price_breaks}

    def get_parameters(self, data: PartData) -> list[Any]:
        if not _INVENTREE_AVAILABLE:
            return [(p.name, p.value) for p in data.parameters]
        from plugin.base.supplier.helpers import ImportParameter

        return [ImportParameter(name=p.name, value=p.value) for p in data.parameters]

    def import_part(
        self,
        data: PartData,
        *,
        category: Any = None,
        creation_user: Any = None,
    ) -> Any:
        from part.models import Part

        part, _created = Part.objects.get_or_create(
            name__iexact=data.name,
            defaults={
                "name": data.name,
                "description": data.description,
                "purchaseable": True,
                "category": category,
                "link": data.link,
            },
        )
        if data.image_url and not part.image:
            try:
                part.set_image_from_url(data.image_url)
            except Exception:
                logger.warning("Failed to download image for part %s", data.sku)
        return part

    def import_manufacturer_part(self, data: PartData, *, part: Any) -> Any:
        if not data.manufacturer_name:
            return None
        from company.models import Company, ManufacturerPart

        manufacturer, _ = Company.objects.get_or_create(
            name__iexact=data.manufacturer_name,
            defaults={"name": data.manufacturer_name, "is_manufacturer": True},
        )
        mfr_part, _ = ManufacturerPart.objects.get_or_create(
            part=part,
            manufacturer=manufacturer,
            MPN=data.manufacturer_part_number,
        )
        return mfr_part

    def import_supplier_part(
        self,
        data: PartData,
        *,
        part: Any,
        manufacturer_part: Any = None,
    ) -> Any:
        from company.models import SupplierPart

        supplier_part, _ = SupplierPart.objects.get_or_create(
            part=part,
            supplier=self.supplier_company,
            SKU=data.sku,
            defaults={"manufacturer_part": manufacturer_part, "link": data.link},
        )
        return supplier_part
