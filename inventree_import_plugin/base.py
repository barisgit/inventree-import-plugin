from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import Any

from inventree_import_plugin import PLUGIN_VERSION
from inventree_import_plugin.compat import SearchResult, Supplier
from inventree_import_plugin.models import PartData

__all__ = [
    "BaseImportPlugin",
    "SearchResult",
    "Supplier",
    "_find_by_normalized_name",
    "_resolve_by_normalized_name",
    "normalize_name",
    "supplier_part_defaults",
    "supplier_part_update_values",
]

logger = logging.getLogger("inventree_import_plugin")


def normalize_name(name: str) -> str:
    """Conservative canonicalization for company/template lookup deduplication.

    Case-folds and removes whitespace / punctuation so simple variants like
    ``Texas Instruments``, ``texasinstruments`` and ``Texas-Instruments`` map
    to the same lookup key. This is still deterministic normalization, not
    fuzzy matching.
    """
    return re.sub(r"[\W_]+", "", name.casefold(), flags=re.UNICODE)


def _resolve_by_normalized_name(
    model_manager: Any,
    raw_name: str,
    *,
    defaults: dict[str, Any] | None = None,
    extra_create_kwargs: dict[str, Any] | None = None,
) -> tuple[Any, bool]:
    """Find or create a DB record by comparing normalized names in Python.

    The DB stores raw, human-readable names (e.g. ``"Texas Instruments"``).
    ``name__iexact`` only does case-insensitive matching — it cannot bridge
    whitespace/punctuation differences.  This helper loads candidate records
    and compares their normalized forms so that ``"Texas Instruments"`` and
    ``"texasinstruments"`` resolve to the same record.

    Returns ``(record, created)`` mirroring Django's ``get_or_create`` API.
    """
    target = normalize_name(raw_name)

    for candidate in model_manager.all():
        candidate_name = getattr(candidate, "name", "")
        if normalize_name(candidate_name) == target:
            return candidate, False

    create_kwargs: dict[str, Any] = {"name": raw_name.strip()}
    if defaults:
        create_kwargs.update(defaults)
    if extra_create_kwargs:
        create_kwargs.update(extra_create_kwargs)
    record = model_manager.create(**create_kwargs)
    return record, True


def _find_by_normalized_name(model_manager: Any, raw_name: str) -> Any | None:
    """Look up a DB record by normalized name without creating one.

    Returns the matching record or ``None``.
    """
    target = normalize_name(raw_name)
    for candidate in model_manager.all():
        candidate_name = getattr(candidate, "name", "")
        if normalize_name(candidate_name) == target:
            return candidate
    return None


def _save_param_with_user(instance: Any, user: Any, update_fields: list[str]) -> None:
    """Save a parameter instance, setting ``updated_by`` when supported."""
    if user is not None and hasattr(instance, "updated_by"):
        instance.updated_by = user
        if "updated_by" not in update_fields:
            update_fields = [*update_fields, "updated_by"]
    instance.save(update_fields=update_fields)


def _create_param_with_user(model: Any, user: Any, **kwargs: Any) -> Any:
    """Create a parameter instance, setting ``updated_by`` when supported."""
    instance = model.objects.create(**kwargs)
    if user is not None and hasattr(instance, "updated_by"):
        instance.updated_by = user
        instance.save(update_fields=["updated_by"])
    return instance


def _enrich_parameters(fresh: PartData) -> list[PartParameter]:
    """Return the provider-supplied parameters."""
    return list(fresh.parameters)


def supplier_part_defaults(data: PartData) -> dict[str, Any]:
    """Build SupplierPart ``defaults`` dict from *data*.

    Extracts supplier-owned fields that should be persisted on every
    ``SupplierPart`` record: ``description``, ``link``, and ``available``.

    Stock / availability fields are included when the provider supplies a
    non-negative integer ``stock`` value in ``extra_data``.
    """
    defaults: dict[str, Any] = {"link": data.link}

    if data.description:
        defaults["description"] = data.description

    stock = data.extra_data.get("stock")
    if isinstance(stock, int) and stock >= 0:
        defaults["available"] = stock

    return defaults


def supplier_part_update_values(
    supplier_part: Any, data: PartData
) -> tuple[dict[str, Any], int | None]:
    """Return changed regular SupplierPart fields and availability quantity."""
    regular_updates: dict[str, Any] = {}
    available_quantity: int | None = None

    for field, value in supplier_part_defaults(data).items():
        if value is None or value == "":
            continue

        current = getattr(supplier_part, field, None)

        if field == "available":
            if current != value:
                available_quantity = value
            continue

        if current != value:
            regular_updates[field] = value

    return regular_updates, available_quantity


def _download_and_set_image(part: Any, image_url: str) -> None:
    """Download *image_url* and save it as the part's image.

    Tries multiple approaches with graceful fallback:
      1. InvenTree.helpers_model.download_image_from_url (current versions)
      2. part.set_image_from_url                    (older versions)
      3. Manual urllib + Django ContentFile         (standalone fallback)
    """
    # 1) InvenTree helper
    try:
        from django.core.files.base import ContentFile
        from InvenTree.helpers_model import download_image_from_url

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
        if not _created:
            _part_updates: dict[str, Any] = {}
            if not part.description and data.description:
                _part_updates["description"] = data.description
            if not part.link and data.link:
                _part_updates["link"] = data.link
            if _part_updates:
                for field, value in _part_updates.items():
                    setattr(part, field, value)
                part.save(update_fields=list(_part_updates.keys()))
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

        manufacturer, _ = _resolve_by_normalized_name(
            Company.objects,
            data.manufacturer_name,
            defaults={"is_manufacturer": True},
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

        defaults = supplier_part_defaults(data)
        defaults["manufacturer_part"] = manufacturer_part

        supplier_part, created = SupplierPart.objects.get_or_create(
            part=part,
            supplier=self.supplier_company,
            SKU=data.sku,
            defaults=defaults,
        )

        if not created:
            regular_updates, available_quantity = supplier_part_update_values(supplier_part, data)

            if regular_updates:
                for field, value in regular_updates.items():
                    setattr(supplier_part, field, value)
                supplier_part.save(update_fields=list(regular_updates.keys()))

            if available_quantity is not None:
                if hasattr(supplier_part, "update_available_quantity"):
                    supplier_part.update_available_quantity(available_quantity)
                else:
                    supplier_part.available = available_quantity
                    supplier_part.save(update_fields=["available"])

        return supplier_part

    # ------------------------------------------------------------------
    # Enrich endpoint (shared by all supplier plugins)
    # ------------------------------------------------------------------

    def _enrich_part(
        self, part_id: int, *, dry_run: bool = False, user: Any = None
    ) -> dict[str, Any]:
        """Fetch fresh supplier data and update enriched fields.

        SupplierPart fields (description, link, available): update-on-change.
        Part description/link: update-on-change.
        Datasheet link: update-on-change (replaces existing attachment URL).
        Parameters and supplier_parameter mirrors: update-on-change.
        Image: add-only (never replaces an existing image).

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

        # SupplierPart supplier-owned fields — update when values change
        regular_updates, available_quantity = supplier_part_update_values(supplier_part, fresh)

        for field in regular_updates:
            updated.append(f"supplier_part:{field}")

        if available_quantity is not None:
            updated.append("supplier_part:available")

        if not dry_run:
            if regular_updates:
                for field, value in regular_updates.items():
                    setattr(supplier_part, field, value)
                supplier_part.save(update_fields=list(regular_updates.keys()))

            if available_quantity is not None:
                if hasattr(supplier_part, "update_available_quantity"):
                    supplier_part.update_available_quantity(available_quantity)
                else:
                    supplier_part.available = available_quantity
                    supplier_part.save(update_fields=["available"])

        # Manufacturer linkage — fill-missing only
        if (
            fresh.manufacturer_name
            and fresh.manufacturer_part_number
            and not getattr(supplier_part, "manufacturer_part", None)
        ):
            if dry_run:
                updated.append("manufacturer_part:link")
            else:
                try:
                    mfr_part = self.import_manufacturer_part(fresh, part=part)
                    if mfr_part is not None:
                        supplier_part.manufacturer_part = mfr_part
                        supplier_part.save(update_fields=["manufacturer_part"])
                        updated.append("manufacturer_part:link")
                except Exception as exc:
                    logger.warning(
                        "Failed to link manufacturer part for SKU %s: %s",
                        supplier_part.SKU,
                        exc,
                    )
                    errors.append(f"manufacturer_part: {exc}")

        # Part description/link — update when values differ
        _part_updates: dict[str, Any] = {}
        if fresh.description and getattr(part, "description", None) != fresh.description:
            _part_updates["description"] = fresh.description
        if fresh.link and getattr(part, "link", None) != fresh.link:
            _part_updates["link"] = fresh.link

        if _part_updates:
            if dry_run:
                for field in _part_updates:
                    updated.append(f"part:{field}")
            else:
                for field, value in _part_updates.items():
                    setattr(part, field, value)
                part.save(update_fields=list(_part_updates.keys()))
                for field in _part_updates:
                    updated.append(f"part:{field}")

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

        # Datasheet link — update-on-change (external-link Part attachment)
        from common.models import Attachment

        _ds_comment = "Datasheet (supplier)"
        _existing_ds = Attachment.objects.filter(
            model_type="part", model_id=part.pk, comment=_ds_comment
        ).first()
        _existing_ds_link = getattr(_existing_ds, "link", None) if _existing_ds else None

        if fresh.datasheet_url and not _existing_ds_link:
            if dry_run:
                updated.append("datasheet_link")
            else:
                try:
                    Attachment.objects.create(
                        model_type="part",
                        model_id=part.pk,
                        link=fresh.datasheet_url,
                        comment=_ds_comment,
                    )
                    updated.append("datasheet_link")
                except Exception as exc:
                    logger.warning(
                        "Failed to create datasheet attachment for part %s: %s", part_id, exc
                    )
                    errors.append(f"datasheet_link: {exc}")
        elif fresh.datasheet_url and _existing_ds_link != fresh.datasheet_url:
            if dry_run:
                updated.append("datasheet_link")
            else:
                try:
                    _existing_ds.link = fresh.datasheet_url
                    _existing_ds.save(update_fields=["link"])
                    updated.append("datasheet_link")
                except Exception as exc:
                    logger.warning(
                        "Failed to update datasheet attachment for part %s: %s", part_id, exc
                    )
                    errors.append(f"datasheet_link: {exc}")
        else:
            skipped.append("datasheet_link")

        # Price breaks — add new quantities or update changed ones
        existing_pb_map: dict[int, Any] = {
            pb.quantity: pb for pb in SupplierPriceBreak.objects.filter(part=supplier_part)
        }
        for pb in fresh.price_breaks:
            existing = existing_pb_map.get(pb.quantity)
            if existing is None:
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
            elif existing.price != pb.price or existing.price_currency != pb.currency:
                if dry_run:
                    updated.append(f"price_break:{pb.quantity}")
                else:
                    try:
                        existing.price = pb.price
                        existing.price_currency = pb.currency
                        existing.save(update_fields=["price", "price_currency"])
                        updated.append(f"price_break:{pb.quantity}")
                    except Exception as exc:
                        errors.append(f"price_break:{pb.quantity}: {exc}")
            else:
                skipped.append(f"price_break:{pb.quantity}")

        # Part parameters — create missing or update changed
        for param in _enrich_parameters(fresh):
            try:
                if dry_run:
                    template = _find_by_normalized_name(
                        parameter_template_model.objects,
                        param.name,
                    )
                    if template is None:
                        updated.append(f"parameter:{param.name}")
                        continue
                else:
                    template, _ = _resolve_by_normalized_name(
                        parameter_template_model.objects,
                        param.name,
                        defaults={"units": param.units},
                    )

                parameter_kwargs = _parameter_filter_kwargs(part, template, content_type_model)
                existing_param = parameter_model.objects.filter(**parameter_kwargs).first()
                if existing_param is None:
                    if dry_run:
                        updated.append(f"parameter:{param.name}")
                    else:
                        _create_param_with_user(
                            parameter_model, user, **parameter_kwargs, data=param.value
                        )
                        updated.append(f"parameter:{param.name}")
                else:
                    current_value = getattr(existing_param, "data", None) or getattr(
                        existing_param, "value", None
                    )
                    if current_value != param.value:
                        if dry_run:
                            updated.append(f"parameter:{param.name}")
                        else:
                            existing_param.data = param.value
                            _save_param_with_user(existing_param, user, ["data"])
                            updated.append(f"parameter:{param.name}")
                    else:
                        skipped.append(f"parameter:{param.name}")

                # Mirror onto SupplierPart when using generic parameter model
                if content_type_model is not None:
                    sp_kwargs = _parameter_filter_kwargs(
                        supplier_part, template, content_type_model
                    )
                    existing_sp_param = parameter_model.objects.filter(**sp_kwargs).first()
                    if existing_sp_param is None:
                        if dry_run:
                            updated.append(f"supplier_parameter:{param.name}")
                        else:
                            _create_param_with_user(
                                parameter_model, user, **sp_kwargs, data=param.value
                            )
                            updated.append(f"supplier_parameter:{param.name}")
                    else:
                        current_sp_value = getattr(existing_sp_param, "data", None) or getattr(
                            existing_sp_param, "value", None
                        )
                        if current_sp_value != param.value:
                            if dry_run:
                                updated.append(f"supplier_parameter:{param.name}")
                            else:
                                existing_sp_param.data = param.value
                                _save_param_with_user(existing_sp_param, user, ["data"])
                                updated.append(f"supplier_parameter:{param.name}")
                        else:
                            skipped.append(f"supplier_parameter:{param.name}")
            except Exception as exc:
                errors.append(f"parameter:{param.name}: {exc}")

        return {"updated": updated, "skipped": skipped, "errors": errors}

    def setup_urls(self) -> list[Any]:
        """Return URL patterns for this plugin, including the enrich endpoint."""
        from django.urls import path
        from InvenTree.permissions import RolePermission
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
                result = plugin._enrich_part(part_id, user=getattr(request, "user", None))
                return Response(result)

        return [path("enrich/<int:part_id>/", _EnrichView.as_view(), name="enrich")]
