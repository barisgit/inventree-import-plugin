"""Test configuration: stub out InvenTree internals that require a running server."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass


def _make_company_stubs() -> dict[str, types.ModuleType]:
    """Return minimal stubs for InvenTree company modules."""
    company_mod = types.ModuleType("company")
    models_mod = types.ModuleType("company.models")

    class _QuerySet:
        def filter(self, **kwargs: object) -> _QuerySet:
            return self

        def select_related(self, *fields: str) -> _QuerySet:
            return self

        def first(self) -> None:
            return None

    class SupplierPart:
        objects = _QuerySet()

    class SupplierPriceBreak:
        objects = _QuerySet()

    models_mod.SupplierPart = SupplierPart  # type: ignore[attr-defined]
    models_mod.SupplierPriceBreak = SupplierPriceBreak  # type: ignore[attr-defined]
    company_mod.models = models_mod  # type: ignore[attr-defined]

    return {"company": company_mod, "company.models": models_mod}


def _make_part_stubs() -> dict[str, types.ModuleType]:
    """Return minimal stubs for InvenTree part modules."""
    part_mod = types.ModuleType("part")
    models_mod = types.ModuleType("part.models")

    class _DoesNotExist(Exception):
        pass

    class _QuerySet:
        def filter(self, **kwargs: object) -> _QuerySet:
            return self

        def exists(self) -> bool:
            return False

    class Part:
        DoesNotExist = _DoesNotExist
        objects = _QuerySet()

    class PartParameterTemplate:
        objects = _QuerySet()

    class PartParameter:
        objects = _QuerySet()

    models_mod.Part = Part  # type: ignore[attr-defined]
    models_mod.PartParameterTemplate = PartParameterTemplate  # type: ignore[attr-defined]
    models_mod.PartParameter = PartParameter  # type: ignore[attr-defined]
    part_mod.models = models_mod  # type: ignore[attr-defined]

    return {"part": part_mod, "part.models": models_mod}


def _make_common_stubs() -> dict[str, types.ModuleType]:
    """Return minimal stubs for InvenTree common modules."""
    common_mod = types.ModuleType("common")
    models_mod = types.ModuleType("common.models")

    class _QuerySet:
        def filter(self, **kwargs: object) -> _QuerySet:
            return self

        def exists(self) -> bool:
            return False

        def first(self) -> None:
            return None

        def create(self, **kwargs: object) -> object:
            return object()

        def get_for_model(self, model: object) -> object:
            return object()

    class ParameterTemplate:
        objects = _QuerySet()

    class Parameter:
        objects = _QuerySet()

    class Attachment:
        objects = _QuerySet()

    models_mod.ParameterTemplate = ParameterTemplate  # type: ignore[attr-defined]
    models_mod.Parameter = Parameter  # type: ignore[attr-defined]
    models_mod.Attachment = Attachment  # type: ignore[attr-defined]
    common_mod.models = models_mod  # type: ignore[attr-defined]

    return {"common": common_mod, "common.models": models_mod}


def _make_django_db_stubs() -> dict[str, types.ModuleType]:
    """Return minimal stubs for django.db."""
    django_mod = types.ModuleType("django")
    django_db_mod = types.ModuleType("django.db")

    class _Transaction:
        @staticmethod
        def atomic() -> object:
            from contextlib import nullcontext

            return nullcontext()

    django_db_mod.transaction = _Transaction  # type: ignore[attr-defined]
    django_mod.db = django_db_mod  # type: ignore[attr-defined]

    return {"django": django_mod, "django.db": django_db_mod}


def _make_django_contenttypes_stubs() -> dict[str, types.ModuleType]:
    """Return minimal stubs for django.contrib.contenttypes."""
    django_contrib_mod = types.ModuleType("django.contrib")
    contenttypes_mod = types.ModuleType("django.contrib.contenttypes")
    contenttypes_models_mod = types.ModuleType("django.contrib.contenttypes.models")

    class _ContentTypeManager:
        def get_for_model(self, model: object) -> object:
            return object()

    class ContentType:
        objects = _ContentTypeManager()

    contenttypes_models_mod.ContentType = ContentType  # type: ignore[attr-defined]
    contenttypes_mod.models = contenttypes_models_mod  # type: ignore[attr-defined]
    django_contrib_mod.contenttypes = contenttypes_mod  # type: ignore[attr-defined]

    return {
        "django.contrib": django_contrib_mod,
        "django.contrib.contenttypes": contenttypes_mod,
        "django.contrib.contenttypes.models": contenttypes_models_mod,
    }


def _make_plugin_stubs() -> dict[str, types.ModuleType]:
    """Return minimal stubs for InvenTree plugin modules."""
    plugin_mod = types.ModuleType("plugin")
    mixins_mod = types.ModuleType("plugin.mixins")
    base_mod = types.ModuleType("plugin.base")
    base_supplier_mod = types.ModuleType("plugin.base.supplier")
    helpers_mod = types.ModuleType("plugin.base.supplier.helpers")

    class SettingsMixin:
        """Minimal stub — provides get_setting used by supplier plugins."""

        SETTINGS: dict = {}

        def get_setting(self, key: str, default: object = None) -> object:
            entry = self.SETTINGS.get(key, {})
            if isinstance(entry, dict):
                return entry.get("default", default)
            return default

    class SupplierMixin(SettingsMixin):
        """Minimal stub — satisfies SupplierMixin import in base.py."""

        supplier_company: object = None

    class InvenTreePlugin(SettingsMixin):
        """Minimal stub — satisfies InvenTreePlugin import in base.py."""

    @dataclass
    class Supplier:
        slug: str
        name: str

    @dataclass
    class SearchResult:
        sku: str
        name: str
        exact: bool
        description: str | None = None
        price: str | None = None
        link: str | None = None
        image_url: str | None = None
        id: str | None = None
        existing_part: object = None

        def __post_init__(self) -> None:
            if not self.id:
                self.id = self.sku

    class UrlsMixin:
        """Minimal stub — satisfies UrlsMixin import in base.py."""

    class UserInterfaceMixin:
        """Minimal stub — satisfies UserInterfaceMixin import in base.py."""

    mixins_mod.SettingsMixin = SettingsMixin  # type: ignore[attr-defined]
    mixins_mod.SupplierMixin = SupplierMixin  # type: ignore[attr-defined]
    mixins_mod.UrlsMixin = UrlsMixin  # type: ignore[attr-defined]
    mixins_mod.UserInterfaceMixin = UserInterfaceMixin  # type: ignore[attr-defined]
    plugin_mod.InvenTreePlugin = InvenTreePlugin  # type: ignore[attr-defined]
    plugin_mod.mixins = mixins_mod  # type: ignore[attr-defined]
    plugin_mod.base = base_mod  # type: ignore[attr-defined]
    base_mod.supplier = base_supplier_mod  # type: ignore[attr-defined]
    helpers_mod.Supplier = Supplier  # type: ignore[attr-defined]
    helpers_mod.SearchResult = SearchResult  # type: ignore[attr-defined]

    return {
        "plugin": plugin_mod,
        "plugin.mixins": mixins_mod,
        "plugin.base": base_mod,
        "plugin.base.supplier": base_supplier_mod,
        "plugin.base.supplier.helpers": helpers_mod,
    }


# Register the stubs before any project module is imported.
if "django" not in sys.modules:
    for _mod_name, _mod in _make_django_db_stubs().items():
        sys.modules[_mod_name] = _mod
if "plugin" not in sys.modules:
    for _mod_name, _mod in _make_plugin_stubs().items():
        sys.modules[_mod_name] = _mod
if "company" not in sys.modules:
    for _mod_name, _mod in _make_company_stubs().items():
        sys.modules[_mod_name] = _mod
if "common" not in sys.modules:
    for _mod_name, _mod in _make_common_stubs().items():
        sys.modules[_mod_name] = _mod
if "django.contrib.contenttypes.models" not in sys.modules:
    for _mod_name, _mod in _make_django_contenttypes_stubs().items():
        sys.modules[_mod_name] = _mod
if "part" not in sys.modules:
    for _mod_name, _mod in _make_part_stubs().items():
        sys.modules[_mod_name] = _mod
