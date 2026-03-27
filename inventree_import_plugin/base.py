from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from inventree_import_plugin import PLUGIN_VERSION
from inventree_import_plugin.models import PartData

if TYPE_CHECKING:
    pass

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


class BaseImportPlugin(_SupplierMixin, _InvenTreePlugin):  # type: ignore[misc]
    VERSION = PLUGIN_VERSION

    def get_pricing_data(self, data: PartData) -> dict[int, tuple[float, str]]:
        return {pb.quantity: (pb.price, pb.currency) for pb in data.price_breaks}

    def get_parameters(self, data: PartData) -> list[Any]:
        if not _INVENTREE_AVAILABLE:
            return [(p.name, p.value) for p in data.parameters]
        from plugin.base.supplier import supplier as supplier_types

        return [supplier_types.ImportParameter(name=p.name, value=p.value) for p in data.parameters]

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
