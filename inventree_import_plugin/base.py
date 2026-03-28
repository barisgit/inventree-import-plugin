from __future__ import annotations

import logging
from io import BytesIO
from dataclasses import dataclass
from typing import Any

from inventree_import_plugin import PLUGIN_VERSION
from inventree_import_plugin.models import PartData

__all__ = ["BaseImportPlugin", "SearchResult", "Supplier"]

logger = logging.getLogger("inventree_import_plugin")


def _download_and_set_image(part: Any, image_url: str) -> None:
    """Download *image_url* and save it as the part's image.

    Tries multiple approaches with graceful fallback:
      1. InvenTree.helpers_model.download_image_from_url (current versions)
      2. part.set_image_from_url                    (older versions)
      3. Manual urllib + Django ContentFile         (standalone fallback)
    """
    # 1) InvenTree helper
    try:
        from InvenTree.helpers_model import download_image_from_url
        from django.core.files.base import ContentFile

        img = download_image_from_url(image_url)
        if img is not None:
            image_format = img.format or "PNG"
            filename = f"part_{getattr(part, 'pk', 'image')}_image.{image_format.lower()}"
            buffer = BytesIO()
            img.save(buffer, format=image_format)
            part.image.save(filename, ContentFile(buffer.getvalue()), save=True)
            return
    except (ImportError, Exception) as exc:
        logger.debug("download_image_from_url unavailable or failed: %s", exc)

    # 2) Legacy method
    if hasattr(part, "set_image_from_url"):
        part.set_image_from_url(image_url)
        return

    # 3) Manual download + Django ContentFile
    import urllib.request

    from django.core.files.base import ContentFile

    filename = image_url.rsplit("/", 1)[-1] or "image.jpg"
    with urllib.request.urlopen(image_url, timeout=15) as resp:
        data = resp.read()
    part.image.save(filename, ContentFile(data), save=True)


def _get_parameter_model_dependencies() -> tuple[Any, Any, Any | None]:
    """Return parameter models for the active InvenTree version."""
    try:
        from common.models import Parameter, ParameterTemplate
        from django.contrib.contenttypes.models import ContentType

        return Parameter, ParameterTemplate, ContentType
    except ImportError:
        from part.models import PartParameter, PartParameterTemplate

        return PartParameter, PartParameterTemplate, None


def _parameter_filter_kwargs(
    part: Any, template: Any, content_type_model: Any | None
) -> dict[str, Any]:
    """Build filter kwargs for either legacy or generic parameter models."""
    if content_type_model is None:
        return {"part": part, "template": template}

    return {
        "model_type": content_type_model.objects.get_for_model(part),
        "model_id": part.pk,
        "template": template,
    }


class _FallbackBase:
    """Stub used when InvenTree is not installed."""


class _FallbackMixin:
    """Stub used when InvenTree is not installed."""


try:
    from plugin import InvenTreePlugin as _InvenTreePlugin
    from plugin.mixins import SupplierMixin as _SupplierMixin
    from plugin.mixins import UrlsMixin as _UrlsMixin
    from plugin.mixins import UserInterfaceMixin as _UserInterfaceMixin

    _INVENTREE_AVAILABLE = True
except ImportError:
    _InvenTreePlugin = _FallbackBase
    _SupplierMixin = _FallbackMixin
    _UrlsMixin = _FallbackMixin
    _UserInterfaceMixin = _FallbackMixin
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


class BaseImportPlugin(_UserInterfaceMixin, _UrlsMixin, _SupplierMixin, _InvenTreePlugin):  # type: ignore[misc]
    VERSION = PLUGIN_VERSION

    def _annotate_existing_parts(self, results: list[SearchResult]) -> None:
        """Set existing_part on each result where a matching SupplierPart already exists."""
        if not _INVENTREE_AVAILABLE:
            return
        from company.models import SupplierPart

        for result in results:
            supplier_part = (
                SupplierPart.objects.filter(supplier=self.supplier_company, SKU=result.sku)
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
                _download_and_set_image(part, data.image_url)
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

    # ------------------------------------------------------------------
    # Enrich endpoint (shared by all supplier plugins)
    # ------------------------------------------------------------------

    def _enrich_part(self, part_id: int, *, dry_run: bool = False) -> dict[str, Any]:
        """Fetch fresh supplier data and fill any gaps on an existing part.

        Only fills missing data — does not overwrite user-edited fields.

        When *dry_run* is ``True`` the method computes what *would* change
        without persisting anything, and returns the preview dict.

        Returns a dict with keys: ``updated``, ``skipped``, ``errors``.
        """
        from company.models import SupplierPart, SupplierPriceBreak
        from part.models import Part

        updated: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []
        parameter_model, parameter_template_model, content_type_model = (
            _get_parameter_model_dependencies()
        )

        try:
            part = Part.objects.get(pk=part_id)
        except Part.DoesNotExist:
            return {"updated": [], "skipped": [], "errors": [f"Part {part_id} not found"]}

        supplier_part = (
            SupplierPart.objects.filter(part=part, supplier=self.supplier_company)
            .select_related("part")
            .first()
        )
        if supplier_part is None:
            return {
                "updated": [],
                "skipped": [],
                "errors": ["No supplier part found for this supplier"],
            }

        suppliers = self.get_suppliers()
        if not suppliers:
            return {"updated": [], "skipped": [], "errors": ["No suppliers configured"]}

        try:
            fresh = self.get_import_data(suppliers[0].slug, supplier_part.SKU)
        except Exception as exc:
            logger.exception("Failed to fetch supplier data for SKU %s", supplier_part.SKU)
            return {"updated": [], "skipped": [], "errors": [str(exc)]}

        if fresh is None:
            return {
                "updated": [],
                "skipped": [],
                "errors": [f"No data returned for SKU {supplier_part.SKU}"],
            }

        # Image — only if the part has none
        if fresh.image_url and not part.image:
            if dry_run:
                updated.append("image")
            else:
                try:
                    _download_and_set_image(part, fresh.image_url)
                    updated.append("image")
                except Exception as exc:
                    logger.warning("Failed to download image for part %s: %s", part_id, exc)
                    errors.append(f"image: {exc}")
        else:
            skipped.append("image")

        # Datasheet link — stored as part.link; only fill if empty
        if fresh.datasheet_url and not part.link:
            if dry_run:
                updated.append("datasheet_link")
            else:
                part.link = fresh.datasheet_url
                part.save(update_fields=["link"])
                updated.append("datasheet_link")
        else:
            skipped.append("datasheet_link")

        # Price breaks — add quantities not already present
        existing_quantities: set[int] = set(
            SupplierPriceBreak.objects.filter(part=supplier_part).values_list("quantity", flat=True)
        )
        for pb in fresh.price_breaks:
            if pb.quantity not in existing_quantities:
                if dry_run:
                    updated.append(f"price_break:{pb.quantity}")
                else:
                    try:
                        SupplierPriceBreak.objects.create(
                            part=supplier_part,
                            quantity=pb.quantity,
                            price=pb.price,
                            price_currency=pb.currency,
                        )
                        updated.append(f"price_break:{pb.quantity}")
                    except Exception as exc:
                        errors.append(f"price_break:{pb.quantity}: {exc}")
            else:
                skipped.append(f"price_break:{pb.quantity}")

        # Parameters — add missing ones (do not overwrite existing values)
        for param in fresh.parameters:
            try:
                if dry_run:
                    template = parameter_template_model.objects.filter(name=param.name).first()
                    if template is None:
                        updated.append(f"parameter:{param.name}")
                        continue
                else:
                    template, _ = parameter_template_model.objects.get_or_create(
                        name=param.name,
                        defaults={"units": param.units},
                    )

                parameter_kwargs = _parameter_filter_kwargs(part, template, content_type_model)
                if not parameter_model.objects.filter(**parameter_kwargs).exists():
                    if dry_run:
                        updated.append(f"parameter:{param.name}")
                    else:
                        parameter_model.objects.create(**parameter_kwargs, data=param.value)
                        updated.append(f"parameter:{param.name}")
                else:
                    skipped.append(f"parameter:{param.name}")
            except Exception as exc:
                errors.append(f"parameter:{param.name}: {exc}")

        return {"updated": updated, "skipped": skipped, "errors": errors}

    def setup_urls(self) -> list[Any]:
        """Return URL patterns for this plugin, including the enrich endpoint."""
        from InvenTree.permissions import RolePermission
        from django.urls import path
        from rest_framework.response import Response
        from rest_framework.views import APIView

        plugin = self

        class _EnrichView(APIView):  # type: ignore[misc]
            permission_classes = [RolePermission]
            role_required = "part.change"

            def get(inner_self, request: Any, part_id: int) -> Any:  # noqa: N805
                """Preview what *would* change without persisting."""
                result = plugin._enrich_part(part_id, dry_run=True)
                return Response(result)

            def post(inner_self, request: Any, part_id: int) -> Any:  # noqa: N805
                result = plugin._enrich_part(part_id)
                return Response(result)

        return [path("enrich/<int:part_id>/", _EnrichView.as_view(), name="enrich")]
