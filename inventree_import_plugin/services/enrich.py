from __future__ import annotations

import logging
from typing import Any, cast

from inventree_import_plugin.base import (
    _download_and_set_image,
    _get_parameter_model_dependencies,
    _parameter_filter_kwargs,
)
from inventree_import_plugin.providers import get_provider_adapters

logger = logging.getLogger(__name__)


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


def enrich_part_for_provider(
    plugin: Any, provider_slug: str, part_id: int, *, dry_run: bool = False
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
            plugin._provider_result(provider_slug, part_id, [], [], [f"Part {part_id} not found"]),
        )

    try:
        supplier_company = plugin.get_supplier_company_for(provider_slug)
    except Exception as exc:
        return cast(
            dict[str, Any], plugin._provider_result(provider_slug, part_id, [], [], [str(exc)])
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
            ),
        )

    try:
        fresh = plugin.get_import_data(provider_slug, supplier_part.SKU)
    except Exception as exc:
        logger.exception(
            "Failed to fetch provider data for %s/%s", provider_slug, supplier_part.SKU
        )
        return cast(
            dict[str, Any], plugin._provider_result(provider_slug, part_id, [], [], [str(exc)])
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
            ),
        )

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

    if fresh.datasheet_url and not part.link:
        if dry_run:
            updated.append("datasheet_link")
        else:
            part.link = fresh.datasheet_url
            part.save(update_fields=["link"])
            updated.append("datasheet_link")
    else:
        skipped.append("datasheet_link")

    existing_quantities: set[int] = set(
        SupplierPriceBreak.objects.filter(part=supplier_part).values_list("quantity", flat=True)
    )
    for price_break in fresh.price_breaks:
        key = f"price_break:{price_break.quantity}"
        if price_break.quantity in existing_quantities:
            skipped.append(key)
            continue

        if dry_run:
            updated.append(key)
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
            key = f"parameter:{param.name}"
            if parameter_model.objects.filter(**parameter_kwargs).exists():
                skipped.append(key)
                continue

            if dry_run:
                updated.append(key)
                continue

            parameter_model.objects.create(**parameter_kwargs, data=param.value)
            updated.append(key)
        except Exception as exc:
            errors.append(f"parameter:{param.name}: {exc}")

    return cast(
        dict[str, Any], plugin._provider_result(provider_slug, part_id, updated, skipped, errors)
    )


def bulk_enrich(
    plugin: Any, part_ids: list[int], provider_slugs: list[str], *, dry_run: bool
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    for part_id in part_ids:
        for provider_slug in provider_slugs:
            results.append(
                enrich_part_for_provider(plugin, provider_slug, part_id, dry_run=dry_run)
            )

    failed = sum(1 for result in results if result["errors"])
    return {
        "results": results,
        "summary": {
            "requested_parts": len(part_ids),
            "provider_count": len(provider_slugs),
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
