from __future__ import annotations

from typing import Any

from inventree_import_plugin import PLUGIN_VERSION
from inventree_import_plugin.api import build_urlpatterns
from inventree_import_plugin.base import BaseImportPlugin
from inventree_import_plugin.compat import SearchResult, Supplier
from inventree_import_plugin.models import PartData
from inventree_import_plugin.providers import get_provider_adapter, get_provider_adapters
from inventree_import_plugin.providers.base import ProviderAdapter
from inventree_import_plugin.services import parse_bulk_payload


class InvenTreeImportPlugin(BaseImportPlugin):
    TITLE = "Supplier Part Import"
    NAME = "InvenTreeImportPlugin"
    SLUG = "inventree-import"
    DESCRIPTION = "Combined supplier import and enrich plugin for LCSC and Mouser"
    VERSION = PLUGIN_VERSION
    AUTHOR = "Blaz Aristovnik"
    LICENSE = "MIT"
    WEBSITE = "https://github.com/barisgit/inventree-import-plugin"
    ADMIN_SOURCE = "Settings.js:renderPluginSettings"

    SETTINGS: dict[str, Any] = {
        "LCSC_ENABLED": {
            "name": "Enable LCSC",
            "description": "Expose LCSC search and enrich features",
            "validator": bool,
            "default": True,
        },
        "LCSC_SUPPLIER": {
            "name": "LCSC Supplier Company",
            "description": "InvenTree supplier company record for LCSC",
            "model": "company.company",
            "model_filters": {"is_supplier": True},
            "required": False,
        },
        "LCSC_DOWNLOAD_IMAGES": {
            "name": "Download LCSC Images",
            "description": "Download part images from LCSC during import and enrich",
            "validator": bool,
            "default": True,
        },
        "MOUSER_ENABLED": {
            "name": "Enable Mouser",
            "description": "Expose Mouser search and enrich features",
            "validator": bool,
            "default": True,
        },
        "MOUSER_SUPPLIER": {
            "name": "Mouser Supplier Company",
            "description": "InvenTree supplier company record for Mouser",
            "model": "company.company",
            "model_filters": {"is_supplier": True},
            "required": False,
        },
        "MOUSER_API_KEY": {
            "name": "Mouser API Key",
            "description": "API key for the Mouser Search API",
            "required": False,
            "protected": True,
        },
        "MOUSER_DOWNLOAD_IMAGES": {
            "name": "Download Mouser Images",
            "description": "Download part images from Mouser during import and enrich",
            "validator": bool,
            "default": True,
        },
        "BULK_BATCH_SIZE": {
            "name": "Bulk Batch Size",
            "description": "Maximum number of part IDs allowed per bulk request",
            "validator": int,
            "default": 50,
        },
    }

    def __init__(self) -> None:
        super().__init__()

        supplier_setting = self.SETTINGS.get("SUPPLIER")
        if isinstance(supplier_setting, dict):
            supplier_setting["required"] = False
            supplier_setting["name"] = "Default Supplier Company"
            supplier_setting["description"] = (
                "Fallback supplier company used when a provider-specific supplier is not configured"
            )

    def get_suppliers(self) -> list[Supplier]:
        return [
            Supplier(slug=adapter.definition.slug, name=adapter.definition.name)
            for adapter in self._get_active_provider_adapters(require_complete_config=True)
        ]

    def get_search_results(self, supplier_slug: str, term: str) -> list[SearchResult]:
        adapter = self._get_provider_adapter(supplier_slug)
        results = adapter.search_results(self, term)
        self._annotate_existing_parts_for_provider(supplier_slug, results)
        return results

    def get_import_data(self, supplier_slug: str, part_id: str) -> PartData | None:
        adapter = self._get_provider_adapter(supplier_slug)
        return adapter.import_data(self, part_id)

    def import_part(
        self,
        data: PartData,
        *,
        category: Any = None,
        creation_user: Any = None,
    ) -> Any:
        data = PartData(
            sku=data.sku,
            name=data.name,
            description=data.description,
            manufacturer_name=data.manufacturer_name,
            manufacturer_part_number=data.manufacturer_part_number,
            link=data.datasheet_url or data.link,
            image_url=data.image_url,
            datasheet_url=data.datasheet_url,
            price_breaks=data.price_breaks,
            parameters=data.parameters,
            extra_data=data.extra_data,
        )
        return super().import_part(data, category=category, creation_user=creation_user)

    def import_supplier_part(
        self,
        data: PartData,
        *,
        part: Any,
        manufacturer_part: Any = None,
    ) -> Any:
        from company.models import SupplierPart

        provider_slug = str(data.extra_data.get("provider_slug") or "")
        supplier_company = self.get_supplier_company_for(provider_slug)

        supplier_part, _ = SupplierPart.objects.get_or_create(
            part=part,
            supplier=supplier_company,
            SKU=data.sku,
            defaults={"manufacturer_part": manufacturer_part, "link": data.link},
        )
        return supplier_part

    _PANEL_TARGET_MODELS = {"part", "partcategory"}

    def get_ui_panels(
        self, request: Any, context: dict[str, Any] | None = None, **kwargs: Any
    ) -> list[dict[str, Any]]:
        target_context = context or {}
        target_model = target_context.get("target_model")

        if target_model not in self._PANEL_TARGET_MODELS:
            return []

        if target_model == "partcategory":
            title = "Enrich Category Parts"
            description = "Preview and apply supplier updates to parts in this category"
        else:
            title = "Enrich Part"
            description = "Preview and apply updates from configured suppliers"

        return [
            {
                "key": "supplier-enrich-v3",
                "title": title,
                "description": description,
                "icon": "ti:refresh-dot:outline",
                "source": self.plugin_static_file("EnrichPanelV3.js:renderEnrichPanelV3"),
                "context": {"plugin_slug": self.SLUG},
            }
        ]

    def get_ui_navigation_items(
        self, request: Any, context: dict[str, Any] | None = None, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return []

    def _get_provider_adapter(self, provider_slug: str) -> ProviderAdapter:
        return get_provider_adapter(provider_slug)

    def _get_active_provider_adapters(self, *, require_complete_config: bool) -> list[Any]:
        adapters: list[Any] = []

        for adapter in get_provider_adapters():
            if not self.get_setting(adapter.definition.enabled_setting_key, True):
                continue

            if require_complete_config and not self._provider_is_configured(
                adapter.definition.slug
            ):
                continue

            adapters.append(adapter)

        return adapters

    def _provider_is_configured(self, provider_slug: str) -> bool:
        adapter = self._get_provider_adapter(provider_slug)
        supplier_pk = self.get_setting(adapter.definition.supplier_setting_key)

        if not supplier_pk:
            return False

        api_key_setting_key = adapter.definition.api_key_setting_key
        if api_key_setting_key:
            api_key = str(self.get_setting(api_key_setting_key, "") or "").strip()
            if not api_key:
                return False

        return True

    def get_supplier_company_for(self, provider_slug: str) -> Any:
        from company.models import Company

        adapter = self._get_provider_adapter(provider_slug)
        supplier_pk = self.get_setting(adapter.definition.supplier_setting_key, None)

        if supplier_pk:
            return Company.objects.get(pk=supplier_pk)

        return self.supplier_company

    def _annotate_existing_parts_for_provider(
        self, provider_slug: str, results: list[SearchResult]
    ) -> None:
        from company.models import SupplierPart

        try:
            supplier_company = self.get_supplier_company_for(provider_slug)
        except Exception:
            return

        for result in results:
            supplier_part = (
                SupplierPart.objects.filter(supplier=supplier_company, SKU=result.sku)
                .select_related("part")
                .first()
            )
            if supplier_part is not None:
                result.existing_part = supplier_part.part

    def _provider_result(
        self,
        provider_slug: str,
        part_id: int,
        updated: list[str],
        skipped: list[str],
        errors: list[str],
        *,
        diff: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        adapter = self._get_provider_adapter(provider_slug)
        result: dict[str, Any] = {
            "provider_slug": provider_slug,
            "provider_name": adapter.definition.name,
            "part_id": part_id,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }
        if diff is not None:
            result["diff"] = diff
        return result

    def _parse_bulk_payload(self, request: Any) -> tuple[list[int], list[str]]:
        return parse_bulk_payload(self, request)

    def setup_urls(self) -> list[Any]:
        return build_urlpatterns(self)
