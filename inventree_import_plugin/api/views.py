from __future__ import annotations

import json
from typing import Any

from inventree_import_plugin.services import (
    bulk_enrich,
    enrich_part_for_provider,
    get_provider_state,
    parse_bulk_payload,
)


def build_urlpatterns(plugin: Any) -> list[Any]:
    from django.middleware.csrf import get_token
    from django.shortcuts import render
    from django.urls import path
    from InvenTree.permissions import RolePermission
    from rest_framework.response import Response
    from rest_framework.views import APIView

    class _BaseRoleView(APIView):  # type: ignore[misc]
        permission_classes = [RolePermission]
        role_required = "part.change"

    class _ProviderStateView(_BaseRoleView):
        def get(inner_self, request: Any, part_id: int) -> Any:  # noqa: N805
            return Response(get_provider_state(plugin, part_id))

    class _PreviewView(_BaseRoleView):
        def get(inner_self, request: Any, part_id: int, provider_slug: str) -> Any:  # noqa: N805
            return Response(enrich_part_for_provider(plugin, provider_slug, part_id, dry_run=True))

    class _ApplyView(_BaseRoleView):
        def post(inner_self, request: Any, part_id: int, provider_slug: str) -> Any:  # noqa: N805
            return Response(enrich_part_for_provider(plugin, provider_slug, part_id, dry_run=False))

    class _BulkPreviewView(_BaseRoleView):
        def post(inner_self, request: Any) -> Any:  # noqa: N805
            try:
                part_ids, provider_slugs = parse_bulk_payload(plugin, request)
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=400)
            return Response(bulk_enrich(plugin, part_ids, provider_slugs, dry_run=True))

    class _BulkApplyView(_BaseRoleView):
        def post(inner_self, request: Any) -> Any:  # noqa: N805
            try:
                part_ids, provider_slugs = parse_bulk_payload(plugin, request)
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=400)
            return Response(bulk_enrich(plugin, part_ids, provider_slugs, dry_run=False))

    class _BulkPageView(_BaseRoleView):
        def get(inner_self, request: Any) -> Any:  # noqa: N805
            active_providers = [
                {
                    "slug": adapter.definition.slug,
                    "name": adapter.definition.name,
                }
                for adapter in plugin._get_active_provider_adapters(require_complete_config=True)
            ]

            context = {
                "bundle_url": plugin.plugin_static_file("bulk/StandaloneBulkPage.js"),
                "mount_context_json": json.dumps(
                    {
                        "pluginSlug": plugin.SLUG,
                        "previewUrl": f"/plugin/{plugin.SLUG}/api/bulk/preview/",
                        "applyUrl": f"/plugin/{plugin.SLUG}/api/bulk/apply/",
                        "csrfToken": get_token(request),
                        "providers": active_providers,
                    }
                ),
            }
            return render(request, "inventree_import_plugin/bulk_page.html", context)

    return [
        path(
            "api/part/<int:part_id>/providers/", _ProviderStateView.as_view(), name="provider-state"
        ),
        path(
            "api/part/<int:part_id>/preview/<str:provider_slug>/",
            _PreviewView.as_view(),
            name="preview-enrich",
        ),
        path(
            "api/part/<int:part_id>/apply/<str:provider_slug>/",
            _ApplyView.as_view(),
            name="apply-enrich",
        ),
        path("api/bulk/preview/", _BulkPreviewView.as_view(), name="bulk-preview"),
        path("api/bulk/apply/", _BulkApplyView.as_view(), name="bulk-apply"),
        path("bulk/", _BulkPageView.as_view(), name="bulk-page"),
    ]
