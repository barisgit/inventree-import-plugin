from __future__ import annotations

import logging
from typing import Any, cast

from inventree_import_plugin.base import (
    _download_and_set_image,
    _get_parameter_model_dependencies,
    _parameter_filter_kwargs,
    supplier_part_defaults,
    supplier_part_update_values,
)
from inventree_import_plugin.providers import get_provider_adapters

logger = logging.getLogger(__name__)

DATASHEET_ATTACHMENT_COMMENT = "Datasheet (supplier)"
"""Stable comment used to tag and identify datasheet link attachments."""


def _key_allowed(key: str, selected_keys: set[str] | None) -> bool:
    """Return True if *key* passes the ``selected_keys`` filter.

    ``None`` means *all keys are allowed* (backward-compatible default).
    """
    return selected_keys is None or key in selected_keys


def _has_datasheet_attachment(part: Any) -> bool:
    """Check whether the part already has a datasheet link attachment."""
    from common.models import Attachment

    return Attachment.objects.filter(
        model_type="part",
        model_id=part.pk,
        comment=DATASHEET_ATTACHMENT_COMMENT,
    ).exists()


def _get_existing_datasheet_link(part: Any) -> str | None:
    """Return the link URL of an existing datasheet attachment, or None."""
    from common.models import Attachment

    att = Attachment.objects.filter(
        model_type="part",
        model_id=part.pk,
        comment=DATASHEET_ATTACHMENT_COMMENT,
    ).first()
    return getattr(att, "link", None) if att else None


def _create_datasheet_attachment(part: Any, datasheet_url: str) -> None:
    """Create an external-link attachment on the part for the datasheet URL."""
    from common.models import Attachment

    Attachment.objects.create(
        model_type="part",
        model_id=part.pk,
        link=datasheet_url,
        comment=DATASHEET_ATTACHMENT_COMMENT,
    )


def get_provider_state(plugin: Any, part_id: int) -> dict[str, Any]:
    from company.models import SupplierPart
    from part.models import Part

    try:
        part = Part.objects.get(pk=part_id)
    except Part.DoesNotExist:
        return {"part_id": part_id, "providers": [], "error": f"Part {part_id} not found"}

    providers: list[dict[str, Any]] = []

    for adapter in get_provider_adapters():
        definition = adapter.definition
        enabled = bool(plugin.get_setting(definition.enabled_setting_key, True))
        configured = plugin._provider_is_configured(definition.slug)
        supplier_part = None
        reason = None

        if not enabled:
            reason = "Disabled in plugin settings"
        elif not configured:
            reason = "Provider settings are incomplete"
        else:
            try:
                supplier_company = plugin.get_supplier_company_for(definition.slug)
                supplier_part = (
                    SupplierPart.objects.filter(part=part, supplier=supplier_company)
                    .select_related("part")
                    .first()
                )
                if supplier_part is None:
                    reason = "No linked supplier part for this provider"
            except Exception as exc:
                reason = str(exc)

        providers.append(
            {
                "slug": definition.slug,
                "name": definition.name,
                "enabled": enabled,
                "configured": configured,
                "can_enrich": reason is None,
                "reason": reason,
                "supplier_part_sku": getattr(supplier_part, "SKU", None),
            }
        )

    return {"part_id": part_id, "providers": providers}


def _build_diff(
    *,
    dry_run: bool,
    part: Any,
    fresh: Any,
    supplier_part: Any | None = None,
    existing_quantities: set[int],
    parameter_model: Any,
    parameter_template_model: Any,
    content_type_model: Any,
) -> dict[str, Any] | None:
    """Build structured diff data for preview responses. Returns None for apply (non-dry-run)."""
    if not dry_run:
        return None

    # SupplierPart diff
    sp_diff_rows: list[dict[str, Any]] = []
    if supplier_part is not None:
        regular_updates, available_quantity = supplier_part_update_values(supplier_part, fresh)
        for field, value in supplier_part_defaults(fresh).items():
            current = getattr(supplier_part, field, None)
            changed = field in regular_updates or (
                field == "available" and available_quantity is not None
            )
            if changed:
                sp_diff_rows.append(
                    {
                        "field": field,
                        "current": current,
                        "incoming": value,
                        "status": "updated" if current else "new",
                    }
                )
            else:
                sp_diff_rows.append(
                    {"field": field, "current": current, "incoming": value, "status": "skipped"}
                )

    # Part description/link diff
    part_field_rows: list[dict[str, Any]] = []
    for field in ("description", "link"):
        current = getattr(part, field, None) or None
        incoming = getattr(fresh, field, None) or None
        changed = not current and incoming
        part_field_rows.append(
            {
                "field": field,
                "current": current,
                "incoming": incoming,
                "status": "new" if changed else "skipped",
            }
        )

    # Image diff
    image_diff: dict[str, Any] | None = None
    if fresh.image_url and not part.image:
        image_diff = {
            "field": "image",
            "current": None,
            "incoming": fresh.image_url,
            "status": "new",
        }
    elif part.image:
        image_diff = {
            "field": "image",
            "current": str(part.image),
            "incoming": fresh.image_url or None,
            "status": "skipped",
        }
    else:
        image_diff = {
            "field": "image",
            "current": None,
            "incoming": fresh.image_url or None,
            "status": "skipped" if not fresh.image_url else "new",
        }

    # Datasheet diff (external-link attachment)
    existing_ds_link = _get_existing_datasheet_link(part)
    datasheet_diff: dict[str, Any] | None = None
    if fresh.datasheet_url and not existing_ds_link:
        datasheet_diff = {
            "field": "datasheet_link",
            "current": None,
            "incoming": fresh.datasheet_url,
            "status": "new",
        }
    elif existing_ds_link:
        datasheet_diff = {
            "field": "datasheet_link",
            "current": existing_ds_link,
            "incoming": fresh.datasheet_url or None,
            "status": "skipped",
        }
    else:
        datasheet_diff = {
            "field": "datasheet_link",
            "current": None,
            "incoming": fresh.datasheet_url or None,
            "status": "skipped" if not fresh.datasheet_url else "new",
        }

    # Price break rows
    price_break_rows: list[dict[str, Any]] = []
    for pb in fresh.price_breaks:
        exists = pb.quantity in existing_quantities
        price_break_rows.append(
            {
                "quantity": pb.quantity,
                "incoming_price": pb.price,
                "incoming_currency": pb.currency,
                "status": "skipped" if exists else "new",
            }
        )

    # Parameter rows
    parameter_rows: list[dict[str, Any]] = []
    for param in fresh.parameters:
        template = parameter_template_model.objects.filter(name=param.name).first()
        current_value = None
        exists = False
        if template is not None:
            parameter_kwargs = _parameter_filter_kwargs(part, template, content_type_model)
            existing_param = parameter_model.objects.filter(**parameter_kwargs).first()
            if existing_param is not None:
                current_value = getattr(existing_param, "data", None) or getattr(
                    existing_param, "value", None
                )
                exists = True
        parameter_rows.append(
            {
                "name": param.name,
                "units": param.units,
                "current": current_value,
                "incoming": param.value,
                "status": "skipped" if exists else "new",
            }
        )

    return {
        "image": image_diff,
        "datasheet": datasheet_diff,
        "price_breaks": price_break_rows,
        "parameters": parameter_rows,
        "part_fields": part_field_rows,
        "supplier_part": sp_diff_rows,
    }


def enrich_part_for_provider(
    plugin: Any,
    provider_slug: str,
    part_id: int,
    *,
    dry_run: bool = False,
    selected_keys: set[str] | None = None,
) -> dict[str, Any]:
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
        return cast(
            dict[str, Any],
            plugin._provider_result(
                provider_slug, part_id, [], [], [f"Part {part_id} not found"], diff=None
            ),
        )

    try:
        supplier_company = plugin.get_supplier_company_for(provider_slug)
    except Exception as exc:
        return cast(
            dict[str, Any],
            plugin._provider_result(provider_slug, part_id, [], [], [str(exc)], diff=None),
        )

    supplier_part = (
        SupplierPart.objects.filter(part=part, supplier=supplier_company)
        .select_related("part")
        .first()
    )
    if supplier_part is None:
        return cast(
            dict[str, Any],
            plugin._provider_result(
                provider_slug,
                part_id,
                [],
                [],
                ["No supplier part found for this provider"],
                diff=None,
            ),
        )

    try:
        fresh = plugin.get_import_data(provider_slug, supplier_part.SKU)
    except Exception as exc:
        logger.exception(
            "Failed to fetch provider data for %s/%s", provider_slug, supplier_part.SKU
        )
        return cast(
            dict[str, Any],
            plugin._provider_result(provider_slug, part_id, [], [], [str(exc)], diff=None),
        )

    if fresh is None:
        return cast(
            dict[str, Any],
            plugin._provider_result(
                provider_slug,
                part_id,
                [],
                [],
                [f"No data returned for SKU {supplier_part.SKU}"],
                diff=None,
            ),
        )

    existing_quantities: set[int] = set(
        SupplierPriceBreak.objects.filter(part=supplier_part).values_list("quantity", flat=True)
    )

    # SupplierPart supplier-owned fields — update when values change
    regular_updates, available_quantity = supplier_part_update_values(supplier_part, fresh)

    for field in regular_updates:
        key = f"supplier_part:{field}"
        if dry_run or _key_allowed(key, selected_keys):
            updated.append(key)
        else:
            skipped.append(key)

    if available_quantity is not None:
        key = "supplier_part:available"
        if dry_run or _key_allowed(key, selected_keys):
            updated.append(key)
        else:
            skipped.append(key)

    if not dry_run:
        allowed_updates = {
            f: v
            for f, v in regular_updates.items()
            if _key_allowed(f"supplier_part:{f}", selected_keys)
        }
        if allowed_updates:
            for field, value in allowed_updates.items():
                setattr(supplier_part, field, value)
            supplier_part.save(update_fields=list(allowed_updates.keys()))

        if available_quantity is not None and _key_allowed(
            "supplier_part:available", selected_keys
        ):
            if hasattr(supplier_part, "update_available_quantity"):
                supplier_part.update_available_quantity(available_quantity)
            else:
                supplier_part.available = available_quantity
                supplier_part.save(update_fields=["available"])

    # Part description/link — fill from supplier data when empty
    _part_updates: dict[str, Any] = {}
    if not getattr(part, "description", None) and fresh.description:
        _part_updates["description"] = fresh.description
    if not getattr(part, "link", None) and fresh.link:
        _part_updates["link"] = fresh.link

    if _part_updates:
        if dry_run:
            for field in _part_updates:
                updated.append(f"part:{field}")
        else:
            allowed_part_updates = {
                f: v for f, v in _part_updates.items() if _key_allowed(f"part:{f}", selected_keys)
            }
            if allowed_part_updates:
                for field, value in allowed_part_updates.items():
                    setattr(part, field, value)
                part.save(update_fields=list(allowed_part_updates.keys()))
                for field in allowed_part_updates:
                    updated.append(f"part:{field}")
            for field in _part_updates:
                if field not in allowed_part_updates:
                    skipped.append(f"part:{field}")

    if fresh.image_url and not part.image:
        if dry_run:
            updated.append("image")
        elif _key_allowed("image", selected_keys):
            try:
                _download_and_set_image(part, fresh.image_url)
                updated.append("image")
            except Exception as exc:
                logger.warning("Failed to download image for part %s: %s", part_id, exc)
                errors.append(f"image: {exc}")
        else:
            skipped.append("image")
    else:
        skipped.append("image")

    if fresh.datasheet_url and not _has_datasheet_attachment(part):
        if dry_run:
            updated.append("datasheet_link")
        elif _key_allowed("datasheet_link", selected_keys):
            try:
                _create_datasheet_attachment(part, fresh.datasheet_url)
                updated.append("datasheet_link")
            except Exception as exc:
                logger.warning(
                    "Failed to create datasheet attachment for part %s: %s", part_id, exc
                )
                errors.append(f"datasheet_link: {exc}")
        else:
            skipped.append("datasheet_link")
    else:
        skipped.append("datasheet_link")

    for price_break in fresh.price_breaks:
        key = f"price_break:{price_break.quantity}"
        if price_break.quantity in existing_quantities:
            skipped.append(key)
            continue

        if dry_run:
            updated.append(key)
            continue

        if not _key_allowed(key, selected_keys):
            skipped.append(key)
            continue

        try:
            SupplierPriceBreak.objects.create(
                part=supplier_part,
                quantity=price_break.quantity,
                price=price_break.price,
                price_currency=price_break.currency,
            )
            updated.append(key)
        except Exception as exc:
            errors.append(f"{key}: {exc}")

    for param in fresh.parameters:
        key = f"parameter:{param.name}"
        try:
            if dry_run:
                template = parameter_template_model.objects.filter(name=param.name).first()
                if template is None:
                    updated.append(key)
                    continue
            else:
                if not _key_allowed(key, selected_keys):
                    skipped.append(key)
                    if content_type_model is not None:
                        skipped.append(f"supplier_parameter:{param.name}")
                    continue
                template, _ = parameter_template_model.objects.get_or_create(
                    name=param.name,
                    defaults={"units": param.units},
                )

            parameter_kwargs = _parameter_filter_kwargs(part, template, content_type_model)
            if parameter_model.objects.filter(**parameter_kwargs).exists():
                skipped.append(key)
            else:
                if dry_run:
                    updated.append(key)
                else:
                    parameter_model.objects.create(**parameter_kwargs, data=param.value)
                    updated.append(key)

            # Mirror onto SupplierPart when using generic parameter model
            if content_type_model is not None:
                sp_kwargs = _parameter_filter_kwargs(supplier_part, template, content_type_model)
                sp_key = f"supplier_parameter:{param.name}"
                if parameter_model.objects.filter(**sp_kwargs).exists():
                    skipped.append(sp_key)
                else:
                    if dry_run:
                        updated.append(sp_key)
                    elif _key_allowed(sp_key, selected_keys):
                        parameter_model.objects.create(**sp_kwargs, data=param.value)
                        updated.append(sp_key)
                    else:
                        skipped.append(sp_key)
        except Exception as exc:
            errors.append(f"parameter:{param.name}: {exc}")

    diff = _build_diff(
        dry_run=dry_run,
        part=part,
        fresh=fresh,
        supplier_part=supplier_part,
        existing_quantities=existing_quantities,
        parameter_model=parameter_model,
        parameter_template_model=parameter_template_model,
        content_type_model=content_type_model,
    )

    return cast(
        dict[str, Any],
        plugin._provider_result(provider_slug, part_id, updated, skipped, errors, diff=diff),
    )


def bulk_enrich(
    plugin: Any,
    part_ids: list[int] | None = None,
    provider_slugs: list[str] | None = None,
    *,
    dry_run: bool,
    operations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    if operations is not None:
        for op in operations:
            results.append(
                enrich_part_for_provider(
                    plugin,
                    op["provider_slug"],
                    op["part_id"],
                    dry_run=dry_run,
                    selected_keys=op.get("selected_keys"),
                )
            )
        requested_parts = len({op["part_id"] for op in operations})
        provider_count = len({op["provider_slug"] for op in operations})
    else:
        for part_id in part_ids or []:
            for provider_slug in provider_slugs or []:
                results.append(
                    enrich_part_for_provider(plugin, provider_slug, part_id, dry_run=dry_run)
                )
        requested_parts = len(part_ids or [])
        provider_count = len(provider_slugs or [])

    failed = sum(1 for result in results if result["errors"])
    return {
        "results": results,
        "summary": {
            "requested_parts": requested_parts,
            "provider_count": provider_count,
            "operations": len(results),
            "failed": failed,
            "succeeded": len(results) - failed,
        },
    }


def parse_bulk_payload(plugin: Any, request: Any) -> tuple[list[int], list[str]]:
    raw_part_ids = request.data.get("part_ids") or []
    raw_provider_slugs = request.data.get("provider_slugs") or []

    if not isinstance(raw_part_ids, list):
        raise ValueError("part_ids must be a list")
    if not isinstance(raw_provider_slugs, list):
        raise ValueError("provider_slugs must be a list")

    try:
        part_ids = sorted({int(part_id) for part_id in raw_part_ids if part_id is not None})
    except (TypeError, ValueError) as exc:
        raise ValueError("part_ids must contain integers") from exc

    provider_slugs = [
        provider_slug
        for provider_slug in raw_provider_slugs
        if isinstance(provider_slug, str)
        and provider_slug in {adapter.definition.slug for adapter in get_provider_adapters()}
    ]

    batch_size = int(plugin.get_setting("BULK_BATCH_SIZE", 50) or 50)
    if len(part_ids) > batch_size:
        raise ValueError(f"Too many part IDs supplied (max {batch_size})")
    if not part_ids:
        raise ValueError("At least one part ID is required")
    if not provider_slugs:
        raise ValueError("At least one provider is required")

    return part_ids, provider_slugs


def parse_bulk_operations(plugin: Any, request: Any) -> list[dict[str, Any]]:
    """Parse the explicit-operations bulk payload format.

    Each operation is ``{part_id, provider_slug, selected_keys?: string[]}``.
    Returns a list of dicts with ``selected_keys`` converted to ``set[str] | None``.
    """
    raw_operations = request.data.get("operations")
    if raw_operations is None:
        raise ValueError("operations is required")
    if not isinstance(raw_operations, list):
        raise ValueError("operations must be a list")

    valid_slugs = {adapter.definition.slug for adapter in get_provider_adapters()}
    batch_size = int(plugin.get_setting("BULK_BATCH_SIZE", 50) or 50)

    operations: list[dict[str, Any]] = []
    for raw_op in raw_operations:
        if not isinstance(raw_op, dict):
            raise ValueError("Each operation must be an object")

        part_id = raw_op.get("part_id")
        provider_slug = raw_op.get("provider_slug")

        if part_id is None:
            raise ValueError("Each operation must have a part_id")
        if provider_slug is None:
            raise ValueError("Each operation must have a provider_slug")

        try:
            part_id = int(part_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("part_id must be an integer") from exc

        if not isinstance(provider_slug, str) or provider_slug not in valid_slugs:
            raise ValueError(f"Invalid provider slug: {provider_slug}")

        raw_keys = raw_op.get("selected_keys")
        if raw_keys is not None:
            if not isinstance(raw_keys, list):
                raise ValueError("selected_keys must be a list of strings")
            if not all(isinstance(k, str) for k in raw_keys):
                raise ValueError("selected_keys must be a list of strings")
            selected_keys: set[str] | None = set(raw_keys)
        else:
            selected_keys = None

        operations.append(
            {
                "part_id": part_id,
                "provider_slug": provider_slug,
                "selected_keys": selected_keys,
            }
        )

    if not operations:
        raise ValueError("At least one operation is required")
    if len(operations) > batch_size:
        raise ValueError(f"Too many operations supplied (max {batch_size})")

    return operations
