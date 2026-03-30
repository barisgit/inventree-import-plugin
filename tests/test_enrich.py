from __future__ import annotations

import sys
import types
from contextlib import nullcontext
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Sequence
from unittest.mock import MagicMock

import json

import pytest

import inventree_import_plugin.base as base_module
import inventree_import_plugin.services.enrich as enrich_module
from inventree_import_plugin.base import BaseImportPlugin, normalize_name
from inventree_import_plugin.models import PartData, PartParameter, PriceBreak


def _ensure_module(monkeypatch: pytest.MonkeyPatch, name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    monkeypatch.setitem(sys.modules, name, module)
    if "." in name:
        parent_name, child_name = name.rsplit(".", 1)
        parent = sys.modules.get(parent_name)
        if parent is None:
            parent = _ensure_module(monkeypatch, parent_name)
        setattr(parent, child_name, module)
    return module


@pytest.fixture(autouse=True)
def runtime(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    part_models = _ensure_module(monkeypatch, "part.models")
    company_models = _ensure_module(monkeypatch, "company.models")
    common_models = _ensure_module(monkeypatch, "common.models")
    django_db = _ensure_module(monkeypatch, "django.db")
    _ensure_module(monkeypatch, "django.contrib.contenttypes.models")

    setattr(django_db, "transaction", SimpleNamespace(atomic=lambda: nullcontext()))

    return SimpleNamespace(
        part_models=part_models,
        company_models=company_models,
        common_models=common_models,
        django_db=django_db,
    )


class _Query:
    def __init__(self, items: Sequence[object]):
        self._items = list(items)

    def first(self):
        return self._items[0] if self._items else None

    def exists(self) -> bool:
        return bool(self._items)

    def select_related(self, *_args, **_kwargs):
        return self

    def values_list(self, field: str, flat: bool = False):
        return [getattr(item, field) for item in self._items]

    def __iter__(self):
        return iter(self._items)


class _PriceBreakRecord:
    def __init__(self, quantity: int, price: float, currency: str):
        self.quantity = quantity
        self.price = price
        self.price_currency = currency
        self.save = MagicMock()


class _MoneyLike:
    """Simulates a django-money Money object."""

    def __init__(self, amount: float, currency: str):
        self.amount = amount
        self.currency = currency

    def __repr__(self):
        return f"Money({self.amount!r}, {self.currency!r})"


class _MoneyPriceBreakRecord:
    """SupplierPriceBreak-like record whose .price is a Money object."""

    def __init__(self, quantity: int, price: float, currency: str):
        self.quantity = quantity
        self.price = _MoneyLike(price, currency)
        self.price_currency = currency
        self.save = MagicMock()


class _AttachmentRecord:
    def __init__(self, *, model_id: int, link: str, comment: str):
        self.model_type = "part"
        self.model_id = model_id
        self.link = link
        self.comment = comment
        self.save = MagicMock()


class _Template:
    def __init__(self, name: str, units: str = ""):
        self.name = name
        self.units = units


class _ParamRecord:
    def __init__(self, template: _Template, model_id: int, value: str):
        self.template = template
        self.model_id = model_id
        self.data = value
        self.save = MagicMock()


class _PartManager:
    def __init__(self, part: object | None, does_not_exist: type[Exception]):
        self.part = part
        self._does_not_exist = does_not_exist

    def get(self, pk: int):
        if self.part is None:
            raise self._does_not_exist(pk)
        return self.part


class _SupplierPartManager:
    def __init__(self, supplier_part: object | None):
        self.supplier_part = supplier_part

    def filter(self, **_kwargs):
        items = [] if self.supplier_part is None else [self.supplier_part]
        return _Query(items)


class _PriceBreakManager:
    def __init__(self, records: Sequence[object] | None = None):
        self.records = list(records or [])

    def filter(self, **_kwargs):
        return _Query(self.records)

    def create(self, **kwargs):
        record = _PriceBreakRecord(
            quantity=kwargs["quantity"],
            price=kwargs["price"],
            currency=kwargs["price_currency"],
        )
        self.records.append(record)
        return record


class _AttachmentManager:
    def __init__(self, attachments: list[_AttachmentRecord] | None = None):
        self.attachments = list(attachments or [])

    def filter(self, **kwargs):
        matches = [
            attachment
            for attachment in self.attachments
            if attachment.model_type == kwargs.get("model_type")
            and attachment.model_id == kwargs.get("model_id")
            and attachment.comment == kwargs.get("comment")
        ]
        return _Query(matches)

    def create(self, **kwargs):
        attachment = _AttachmentRecord(
            model_id=kwargs["model_id"],
            link=kwargs["link"],
            comment=kwargs["comment"],
        )
        self.attachments.append(attachment)
        return attachment


class _TemplateManager:
    def __init__(self, templates: list[_Template] | None = None):
        self.templates: list[_Template] = list(templates or [])

    def all(self):
        return list(self.templates)

    def filter(self, **kwargs):
        name = kwargs.get("name") or kwargs.get("name__iexact")
        key = normalize_name(name) if isinstance(name, str) else ""
        match = None
        for t in self.templates:
            if normalize_name(t.name) == key:
                match = t
                break
        return _Query([] if match is None else [match])

    def get_or_create(
        self,
        name: str | None = None,
        *,
        name__iexact: str | None = None,
        defaults: dict[str, str] | None = None,
        **_kwargs,
    ):
        lookup = name__iexact if name__iexact is not None else name
        key = normalize_name(lookup) if lookup else ""
        for t in self.templates:
            if normalize_name(t.name) == key:
                return t, False
        display_name = (defaults or {}).get("name", name or lookup or "")
        template = _Template(name=display_name, units=(defaults or {}).get("units", ""))
        self.templates.append(template)
        return template, True

    def create(self, **kwargs):
        template = _Template(name=kwargs["name"], units=kwargs.get("units", ""))
        self.templates.append(template)
        return template


class _ParamManager:
    def __init__(self, records: list[_ParamRecord] | None = None):
        self.records = list(records or [])

    def filter(self, **kwargs):
        template = kwargs["template"]
        model_id = kwargs.get("model_id", getattr(kwargs.get("part"), "pk", None))
        matches = [
            record
            for record in self.records
            if record.template is template and record.model_id == model_id
        ]
        return _Query(matches)

    def create(self, **kwargs):
        template = kwargs["template"]
        model_id = kwargs.get("model_id", getattr(kwargs.get("part"), "pk", None))
        if not isinstance(model_id, int):
            raise AssertionError("model_id must be an int in tests")
        record = _ParamRecord(template=template, model_id=model_id, value=kwargs["data"])
        self.records.append(record)
        return record


class _ContentTypeObjects:
    @staticmethod
    def get_for_model(_obj):
        return "content-type"


class _ContentTypeModel:
    objects = _ContentTypeObjects()


class _CompanyRecord:
    def __init__(self, name: str, is_manufacturer: bool = True):
        self.name = name
        self.is_manufacturer = is_manufacturer
        self.save = MagicMock()


class _CompanyManager:
    def __init__(self, companies: list[_CompanyRecord] | None = None):
        self.companies: list[_CompanyRecord] = list(companies or [])

    def all(self):
        return list(self.companies)

    def get_or_create(self, *, name__iexact: str = "", defaults: dict | None = None, **_kwargs):
        key = normalize_name(name__iexact)
        for c in self.companies:
            if normalize_name(c.name) == key:
                return c, False
        name = (defaults or {}).get("name", name__iexact)
        company = _CompanyRecord(
            name=name, is_manufacturer=(defaults or {}).get("is_manufacturer", True)
        )
        self.companies.append(company)
        return company, True

    def create(self, **kwargs):
        company = _CompanyRecord(
            name=kwargs["name"],
            is_manufacturer=kwargs.get("is_manufacturer", True),
        )
        self.companies.append(company)
        return company


class _ManufacturerPartRecord:
    def __init__(self, part: object, manufacturer: _CompanyRecord, MPN: str):
        self.part = part
        self.manufacturer = manufacturer
        self.MPN = MPN
        self.save = MagicMock()


class _ManufacturerPartManager:
    def __init__(self, records: list[_ManufacturerPartRecord] | None = None):
        self.records = list(records or [])

    def get_or_create(
        self,
        *,
        part: object,
        manufacturer: _CompanyRecord,
        MPN: str,
        defaults: dict | None = None,
        **_kwargs,
    ):
        for rec in self.records:
            if rec.part is part and rec.manufacturer is manufacturer and rec.MPN == MPN:
                return rec, False
        rec = _ManufacturerPartRecord(part=part, manufacturer=manufacturer, MPN=MPN)
        self.records.append(rec)
        return rec, True


@dataclass
class _Harness:
    part: MagicMock
    supplier_part: MagicMock
    price_break_manager: _PriceBreakManager
    attachment_manager: _AttachmentManager
    template_manager: _TemplateManager
    parameter_manager: _ParamManager
    company_manager: _CompanyManager
    manufacturer_part_manager: _ManufacturerPartManager
    download_base: MagicMock
    download_service: MagicMock


class _BasePlugin(BaseImportPlugin):
    supplier_company = "supplier"

    def __init__(self, fresh: PartData):
        self._fresh = fresh

    def get_suppliers(self):
        return [SimpleNamespace(slug="test-provider")]

    def get_import_data(self, _provider_slug: str, _sku: str):
        return self._fresh


class _ServicePlugin:
    def __init__(self, fresh: PartData):
        self._fresh = fresh

    def get_supplier_company_for(self, _provider_slug: str):
        return "supplier"

    def get_import_data(self, _provider_slug: str, _sku: str):
        return self._fresh

    def get_setting(self, _key: str, default=None):
        return default

    def _provider_result(self, provider_slug, part_id, updated, skipped, errors, diff=None):
        result = {
            "provider_slug": provider_slug,
            "provider_name": provider_slug,
            "part_id": part_id,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }
        if diff is not None:
            result["diff"] = diff
        return result


def _make_fresh(**overrides) -> PartData:
    data = PartData(
        sku="C12345",
        name="LM358",
        description="New description",
        manufacturer_name="TI",
        manufacturer_part_number="LM358",
        link="https://example.com/new-link",
        image_url="https://example.com/image.png",
        datasheet_url="https://example.com/new-datasheet.pdf",
        price_breaks=[PriceBreak(quantity=1, price=0.15, currency="EUR")],
        parameters=[PartParameter(name="Voltage", value="5V", units="V")],
        extra_data={"stock": 100},
    )
    for key, value in overrides.items():
        setattr(data, key, value)
    return data


def _make_part(
    *,
    description: str = "Current description",
    link: str = "https://example.com/current-link",
    image: str = "",
) -> MagicMock:
    part = MagicMock()
    part.pk = 42
    part.description = description
    part.link = link
    part.image = image
    part.save = MagicMock()
    return part


def _make_supplier_part(
    *,
    description: str = "Supplier current description",
    link: str = "https://example.com/supplier-current-link",
    available: int = 10,
) -> MagicMock:
    supplier_part = MagicMock()
    supplier_part.pk = 84
    supplier_part.SKU = "C12345"
    supplier_part.description = description
    supplier_part.link = link
    supplier_part.available = available
    supplier_part.save = MagicMock()
    supplier_part.update_available_quantity = MagicMock()
    return supplier_part


def _install_backend(
    monkeypatch: pytest.MonkeyPatch,
    runtime: SimpleNamespace,
    *,
    part: MagicMock | None = None,
    supplier_part: MagicMock | None = None,
    price_breaks: Sequence[object] | None = None,
    attachments: list[_AttachmentRecord] | None = None,
    templates: list[_Template] | None = None,
    parameters: list[_ParamRecord] | None = None,
) -> _Harness:
    part = part or _make_part()
    supplier_part = supplier_part or _make_supplier_part()

    part_does_not_exist = type("DoesNotExist", (Exception,), {})
    PartModel = type(
        "Part",
        (),
        {"DoesNotExist": part_does_not_exist, "objects": _PartManager(part, part_does_not_exist)},
    )
    SupplierPartModel = type("SupplierPart", (), {"objects": _SupplierPartManager(supplier_part)})
    price_break_manager = _PriceBreakManager(price_breaks)
    SupplierPriceBreakModel = type("SupplierPriceBreak", (), {"objects": price_break_manager})
    attachment_manager = _AttachmentManager(attachments)
    AttachmentModel = type("Attachment", (), {"objects": attachment_manager})
    template_manager = _TemplateManager(templates)
    TemplateModel = type("ParameterTemplate", (), {"objects": template_manager})
    parameter_manager = _ParamManager(parameters)
    ParameterModel = type("Parameter", (), {"objects": parameter_manager})

    runtime.part_models.Part = PartModel
    runtime.company_models.SupplierPart = SupplierPartModel
    runtime.company_models.SupplierPriceBreak = SupplierPriceBreakModel
    runtime.common_models.Attachment = AttachmentModel

    company_manager = _CompanyManager()
    CompanyModel = type("Company", (), {"objects": company_manager})
    runtime.company_models.Company = CompanyModel

    manufacturer_part_manager = _ManufacturerPartManager()
    ManufacturerPartModel = type("ManufacturerPart", (), {"objects": manufacturer_part_manager})
    runtime.company_models.ManufacturerPart = ManufacturerPartModel

    deps = (ParameterModel, TemplateModel, _ContentTypeModel)
    monkeypatch.setattr(base_module, "_get_parameter_model_dependencies", lambda: deps)
    monkeypatch.setattr(enrich_module, "_get_parameter_model_dependencies", lambda: deps)

    download_base = MagicMock()
    download_service = MagicMock()
    monkeypatch.setattr(base_module, "_download_and_set_image", download_base)
    monkeypatch.setattr(enrich_module, "_download_and_set_image", download_service)

    return _Harness(
        part=part,
        supplier_part=supplier_part,
        price_break_manager=price_break_manager,
        attachment_manager=attachment_manager,
        template_manager=template_manager,
        parameter_manager=parameter_manager,
        company_manager=company_manager,
        manufacturer_part_manager=manufacturer_part_manager,
        download_base=download_base,
        download_service=download_service,
    )


def _run_base(
    monkeypatch: pytest.MonkeyPatch,
    runtime: SimpleNamespace,
    *,
    dry_run: bool = False,
    fresh: PartData | None = None,
    part: MagicMock | None = None,
    supplier_part: MagicMock | None = None,
    price_breaks: Sequence[object] | None = None,
    attachments: list[_AttachmentRecord] | None = None,
    templates: list[_Template] | None = None,
    parameters: list[_ParamRecord] | None = None,
    user: Any = None,
):
    harness = _install_backend(
        monkeypatch,
        runtime,
        part=part,
        supplier_part=supplier_part,
        price_breaks=price_breaks,
        attachments=attachments,
        templates=templates,
        parameters=parameters,
    )
    plugin = _BasePlugin(fresh or _make_fresh())
    result = plugin._enrich_part(harness.part.pk, dry_run=dry_run, user=user)
    return result, harness


def _run_service(
    monkeypatch: pytest.MonkeyPatch,
    runtime: SimpleNamespace,
    *,
    dry_run: bool = False,
    selected_keys: set[str] | None = None,
    fresh: PartData | None = None,
    part: MagicMock | None = None,
    supplier_part: MagicMock | None = None,
    price_breaks: Sequence[object] | None = None,
    attachments: list[_AttachmentRecord] | None = None,
    templates: list[_Template] | None = None,
    parameters: list[_ParamRecord] | None = None,
    user: Any = None,
):
    harness = _install_backend(
        monkeypatch,
        runtime,
        part=part,
        supplier_part=supplier_part,
        price_breaks=price_breaks,
        attachments=attachments,
        templates=templates,
        parameters=parameters,
    )
    plugin = _ServicePlugin(fresh or _make_fresh())
    result = enrich_module.enrich_part_for_provider(
        plugin,
        "test-provider",
        harness.part.pk,
        dry_run=dry_run,
        selected_keys=selected_keys,
        user=user,
    )
    return result, harness


class TestParseBulkOperations:
    def test_valid_operations(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            enrich_module,
            "get_provider_adapters",
            lambda: [SimpleNamespace(definition=SimpleNamespace(slug="test-provider"))],
        )
        plugin = SimpleNamespace(get_setting=lambda _key, default=None: default)
        request = SimpleNamespace(
            data={
                "operations": [
                    {"part_id": 1, "provider_slug": "test-provider", "selected_keys": ["image"]},
                    {"part_id": 2, "provider_slug": "test-provider"},
                ]
            }
        )

        result = enrich_module.parse_bulk_operations(plugin, request)

        assert result[0]["selected_keys"] == {"image"}
        assert result[1]["selected_keys"] is None

    def test_rejects_non_string_selected_keys(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            enrich_module,
            "get_provider_adapters",
            lambda: [SimpleNamespace(definition=SimpleNamespace(slug="test-provider"))],
        )
        plugin = SimpleNamespace(get_setting=lambda _key, default=None: default)
        request = SimpleNamespace(
            data={
                "operations": [
                    {"part_id": 1, "provider_slug": "test-provider", "selected_keys": ["image", 1]}
                ]
            }
        )

        with pytest.raises(ValueError, match="selected_keys must be a list of strings"):
            enrich_module.parse_bulk_operations(plugin, request)

    def test_rejects_unknown_provider(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(enrich_module, "get_provider_adapters", lambda: [])
        plugin = SimpleNamespace(get_setting=lambda _key, default=None: default)
        request = SimpleNamespace(data={"operations": [{"part_id": 1, "provider_slug": "missing"}]})

        with pytest.raises(ValueError, match="Invalid provider slug"):
            enrich_module.parse_bulk_operations(plugin, request)


class TestBulkEnrich:
    def test_operations_payload_is_forwarded(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[tuple[int, str, set[str] | None]] = []

        def _fake_enrich(
            _plugin, provider_slug, part_id, *, dry_run, selected_keys=None, user=None
        ):
            calls.append((part_id, provider_slug, selected_keys))
            return {"updated": [], "skipped": [], "errors": []}

        monkeypatch.setattr(enrich_module, "enrich_part_for_provider", _fake_enrich)

        result = enrich_module.bulk_enrich(
            SimpleNamespace(),
            dry_run=False,
            operations=[
                {"part_id": 5, "provider_slug": "test-provider", "selected_keys": {"image"}}
            ],
        )

        assert calls == [(5, "test-provider", {"image"})]
        assert result["summary"]["operations"] == 1

    def test_legacy_bulk_summary_counts_errors(self, monkeypatch: pytest.MonkeyPatch):
        responses = iter(
            [
                {"updated": [], "skipped": [], "errors": []},
                {"updated": [], "skipped": [], "errors": ["boom"]},
            ]
        )
        monkeypatch.setattr(
            enrich_module, "enrich_part_for_provider", lambda *_args, **_kwargs: next(responses)
        )

        result = enrich_module.bulk_enrich(
            SimpleNamespace(),
            part_ids=[1],
            provider_slugs=["a", "b"],
            dry_run=True,
        )

        assert result["summary"]["failed"] == 1
        assert result["summary"]["succeeded"] == 1


class TestServiceEnrich:
    def test_part_fields_update_on_change(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        result, harness = _run_service(monkeypatch, runtime)

        assert "part:description" in result["updated"]
        assert "part:link" in result["updated"]
        harness.part.save.assert_called_once()

    def test_selected_keys_gate_part_field_updates(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        result, harness = _run_service(
            monkeypatch,
            runtime,
            selected_keys={"part:description"},
        )

        assert "part:description" in result["updated"]
        assert "part:link" in result["skipped"]
        assert harness.part.description == "New description"
        assert harness.part.link == "https://example.com/current-link"

    def test_image_remains_add_only(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        result, harness = _run_service(
            monkeypatch,
            runtime,
            part=_make_part(image="existing.png"),
        )

        assert "image" in result["skipped"]
        harness.download_service.assert_not_called()

    def test_datasheet_updates_when_changed(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        attachment = _AttachmentRecord(
            model_id=42,
            link="https://example.com/old-datasheet.pdf",
            comment=enrich_module.DATASHEET_ATTACHMENT_COMMENT,
        )
        result, harness = _run_service(monkeypatch, runtime, attachments=[attachment])

        assert "datasheet_link" in result["updated"]
        assert attachment.link == "https://example.com/new-datasheet.pdf"
        attachment.save.assert_called_once_with(update_fields=["link"])
        assert harness.attachment_manager.attachments[0] is attachment

    def test_price_break_updates_when_currency_changes(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        existing = _PriceBreakRecord(quantity=1, price=0.15, currency="USD")
        result, _ = _run_service(monkeypatch, runtime, price_breaks=[existing])

        assert "price_break:1" in result["updated"]
        assert existing.price_currency == "EUR"
        existing.save.assert_called_once_with(update_fields=["price", "price_currency"])

    def test_parameter_and_supplier_parameter_update_on_change(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        template = _Template("Voltage", "V")
        part_param = _ParamRecord(template=template, model_id=42, value="3V")
        supplier_param = _ParamRecord(template=template, model_id=84, value="3V")
        result, _ = _run_service(
            monkeypatch,
            runtime,
            templates=[template],
            parameters=[part_param, supplier_param],
        )

        assert "parameter:Voltage" in result["updated"]
        assert "supplier_parameter:Voltage" in result["updated"]
        assert part_param.data == "5V"
        assert supplier_param.data == "5V"
        part_param.save.assert_called_once_with(update_fields=["data"])
        supplier_param.save.assert_called_once_with(update_fields=["data"])

    def test_supplier_parameter_only_selection_is_no_op(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        result, harness = _run_service(
            monkeypatch,
            runtime,
            selected_keys={"supplier_parameter:Voltage"},
        )

        assert "parameter:Voltage" in result["skipped"]
        assert "supplier_parameter:Voltage" in result["skipped"]
        assert harness.parameter_manager.records == []

    def test_preview_diff_reports_updated_values(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        template = _Template("Voltage", "V")
        part_param = _ParamRecord(template=template, model_id=42, value="3V")
        attachment = _AttachmentRecord(
            model_id=42,
            link="https://example.com/old-datasheet.pdf",
            comment=enrich_module.DATASHEET_ATTACHMENT_COMMENT,
        )
        existing_pb = _PriceBreakRecord(quantity=1, price=0.10, currency="USD")
        result, _ = _run_service(
            monkeypatch,
            runtime,
            dry_run=True,
            templates=[template],
            parameters=[part_param],
            attachments=[attachment],
            price_breaks=[existing_pb],
        )

        diff = result["diff"]
        part_fields = {row["field"]: row for row in diff["part_fields"]}
        assert part_fields["description"]["status"] == "updated"
        assert diff["datasheet"]["status"] == "updated"
        assert diff["parameters"][0]["status"] == "updated"
        assert diff["price_breaks"][0]["status"] == "updated"
        assert diff["price_breaks"][0]["current_currency"] == "USD"
        assert diff["price_breaks"][0]["incoming_currency"] == "EUR"


class TestServiceTransactions:
    def test_apply_mode_enters_atomic_context(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        calls: list[str] = []

        class _Atomic:
            def __enter__(self):
                calls.append("enter")

            def __exit__(self, exc_type, exc, tb):
                calls.append("exit")

        runtime.django_db.transaction = SimpleNamespace(atomic=lambda: _Atomic())

        _run_service(monkeypatch, runtime, dry_run=False)

        assert calls == ["enter", "exit"]

    def test_preview_mode_does_not_enter_atomic_context(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        calls: list[str] = []

        class _Atomic:
            def __enter__(self):
                calls.append("enter")

            def __exit__(self, exc_type, exc, tb):
                calls.append("exit")

        runtime.django_db.transaction = SimpleNamespace(atomic=lambda: _Atomic())

        _run_service(monkeypatch, runtime, dry_run=True)

        assert calls == []

    def test_apply_failure_propagates_out_of_transaction(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        calls: list[str] = []

        class _Atomic:
            def __enter__(self):
                calls.append("enter")

            def __exit__(self, exc_type, exc, tb):
                calls.append("exit")

        runtime.django_db.transaction = SimpleNamespace(atomic=lambda: _Atomic())
        part = _make_part()
        part.save.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            _run_service(monkeypatch, runtime, part=part)

        assert calls == ["enter", "exit"]


class TestBaseEnrich:
    def test_part_fields_update_on_change(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        result, harness = _run_base(monkeypatch, runtime)

        assert "part:description" in result["updated"]
        assert "part:link" in result["updated"]
        harness.part.save.assert_called_once()

    def test_datasheet_updates_when_changed(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        attachment = _AttachmentRecord(
            model_id=42,
            link="https://example.com/old-datasheet.pdf",
            comment="Datasheet (supplier)",
        )
        result, _ = _run_base(monkeypatch, runtime, attachments=[attachment])

        assert "datasheet_link" in result["updated"]
        assert attachment.link == "https://example.com/new-datasheet.pdf"
        attachment.save.assert_called_once_with(update_fields=["link"])

    def test_price_break_updates_when_changed(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        existing = _PriceBreakRecord(quantity=1, price=0.10, currency="USD")
        result, _ = _run_base(monkeypatch, runtime, price_breaks=[existing])

        assert "price_break:1" in result["updated"]
        assert existing.price == 0.15
        assert existing.price_currency == "EUR"
        existing.save.assert_called_once_with(update_fields=["price", "price_currency"])

    def test_parameters_and_supplier_mirror_update_on_change(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        template = _Template("Voltage", "V")
        part_param = _ParamRecord(template=template, model_id=42, value="3V")
        supplier_param = _ParamRecord(template=template, model_id=84, value="3V")
        result, _ = _run_base(
            monkeypatch,
            runtime,
            templates=[template],
            parameters=[part_param, supplier_param],
        )

        assert "parameter:Voltage" in result["updated"]
        assert "supplier_parameter:Voltage" in result["updated"]
        assert part_param.data == "5V"
        assert supplier_param.data == "5V"
        part_param.save.assert_called_once_with(update_fields=["data"])
        supplier_param.save.assert_called_once_with(update_fields=["data"])


class TestMoneyPriceBreakRegression:
    """Regression tests for Money-object handling in price-break diffs."""

    def test_to_numeric_extracts_amount_from_money_like(self):
        money = _MoneyLike(1.23, "EUR")
        assert enrich_module._to_numeric(money) == 1.23
        assert isinstance(enrich_module._to_numeric(money), float)

    def test_to_numeric_passes_plain_float(self):
        assert enrich_module._to_numeric(0.15) == 0.15
        assert enrich_module._to_numeric(5) == 5.0
        assert enrich_module._to_numeric(None) is None

    def test_preview_diff_json_safe_with_money_price(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        existing = _MoneyPriceBreakRecord(quantity=1, price=0.10, currency="USD")
        result, _ = _run_service(monkeypatch, runtime, dry_run=True, price_breaks=[existing])

        diff = result["diff"]
        # Must not raise -- proves JSON-serializable
        serialized = json.dumps(diff)
        assert '"current_price": 0.1' in serialized or '"current_price":0.1' in serialized
        assert diff["price_breaks"][0]["status"] == "updated"
        assert diff["price_breaks"][0]["current_price"] == 0.10

    def test_apply_skips_when_money_price_matches(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        existing = _MoneyPriceBreakRecord(quantity=1, price=0.15, currency="EUR")
        result, _ = _run_service(monkeypatch, runtime, dry_run=False, price_breaks=[existing])

        assert "price_break:1" in result["skipped"]
        existing.save.assert_not_called()

    def test_apply_updates_when_money_price_differs(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        existing = _MoneyPriceBreakRecord(quantity=1, price=0.10, currency="USD")
        result, _ = _run_service(monkeypatch, runtime, dry_run=False, price_breaks=[existing])

        assert "price_break:1" in result["updated"]
        existing.save.assert_called_once_with(update_fields=["price", "price_currency"])


class TestBaseManufacturerEnrich:
    def test_manufacturer_linked_when_missing(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, harness = _run_base(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
        )

        assert "manufacturer_part:link" in result["updated"]
        assert harness.manufacturer_part_manager.records
        mfr_part = harness.manufacturer_part_manager.records[0]
        assert mfr_part.MPN == "LM358"
        assert mfr_part.manufacturer.name == "TI"

    def test_manufacturer_skipped_when_already_linked(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = MagicMock()
        result, _ = _run_base(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
        )

        assert "manufacturer_part:link" not in result["updated"]

    def test_manufacturer_skipped_when_no_mfr_data(self, monkeypatch, runtime):
        fresh = _make_fresh(manufacturer_name="", manufacturer_part_number="")
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, _ = _run_base(
            monkeypatch,
            runtime,
            fresh=fresh,
            supplier_part=supplier_part,
        )

        assert "manufacturer_part:link" not in result["updated"]

    def test_manufacturer_dry_run_does_not_link(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, harness = _run_base(
            monkeypatch,
            runtime,
            dry_run=True,
            supplier_part=supplier_part,
        )

        assert "manufacturer_part:link" in result["updated"]
        assert not harness.manufacturer_part_manager.records


class TestServiceManufacturerEnrich:
    def test_manufacturer_linked_when_missing(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, harness = _run_service(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
        )

        assert "manufacturer_part:link" in result["updated"]
        assert harness.manufacturer_part_manager.records
        mfr_part = harness.manufacturer_part_manager.records[0]
        assert mfr_part.MPN == "LM358"
        assert mfr_part.manufacturer.name == "TI"

    def test_manufacturer_skipped_when_already_linked(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = MagicMock()
        result, _ = _run_service(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
        )

        assert "manufacturer_part:link" not in result["updated"]

    def test_manufacturer_skipped_by_selected_keys(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, _ = _run_service(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
            selected_keys={"part:description"},
        )

        assert "manufacturer_part:link" in result["skipped"]

    def test_preview_diff_includes_manufacturer_part(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, _ = _run_service(
            monkeypatch,
            runtime,
            dry_run=True,
            supplier_part=supplier_part,
        )

        diff = result["diff"]
        mfr_rows = diff["manufacturer_part"]
        assert len(mfr_rows) == 2
        fields = {row["field"]: row for row in mfr_rows}
        assert fields["manufacturer_name"]["status"] == "new"
        assert fields["manufacturer_name"]["incoming"] == "TI"
        assert fields["manufacturer_part_number"]["status"] == "new"
        assert fields["manufacturer_part_number"]["incoming"] == "LM358"

    def test_preview_diff_empty_when_manufacturer_already_linked(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = MagicMock()
        result, _ = _run_service(
            monkeypatch,
            runtime,
            dry_run=True,
            supplier_part=supplier_part,
        )

        diff = result["diff"]
        assert diff["manufacturer_part"] == []


class TestServiceManufacturerSelectedKeysRegression:
    """Regression: selecting manufacturer_part field keys must enable linking.

    The preview diff exposes selectable rows like
    ``manufacturer_part:manufacturer_name`` and
    ``manufacturer_part:manufacturer_part_number``.  The backend must treat
    any of those as permitting manufacturer creation/linkage, not only the
    synthetic ``manufacturer_part:link`` key.
    """

    def test_field_key_manufacturer_name_enables_link(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, harness = _run_service(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
            selected_keys={"manufacturer_part:manufacturer_name"},
        )

        assert "manufacturer_part:link" in result["updated"]
        assert harness.manufacturer_part_manager.records

    def test_field_key_manufacturer_part_number_enables_link(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, harness = _run_service(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
            selected_keys={"manufacturer_part:manufacturer_part_number"},
        )

        assert "manufacturer_part:link" in result["updated"]
        assert harness.manufacturer_part_manager.records

    def test_both_field_keys_enables_link(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, harness = _run_service(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
            selected_keys={
                "manufacturer_part:manufacturer_name",
                "manufacturer_part:manufacturer_part_number",
            },
        )

        assert "manufacturer_part:link" in result["updated"]
        assert harness.manufacturer_part_manager.records

    def test_synthetic_link_key_still_works(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, harness = _run_service(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
            selected_keys={"manufacturer_part:link"},
        )

        assert "manufacturer_part:link" in result["updated"]
        assert harness.manufacturer_part_manager.records

    def test_unrelated_key_skips_manufacturer(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, _ = _run_service(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
            selected_keys={"part:description"},
        )

        assert "manufacturer_part:link" in result["skipped"]


class TestBaseManufacturerErrorReporting:
    """Regression: base.py legacy enrich path must append error on failure."""

    def test_manufacturer_link_failure_appends_error(self, monkeypatch, runtime):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None

        def _failing_import(_self, data, *, part):
            raise RuntimeError("DB connection lost")

        harness = _install_backend(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
        )
        plugin = _BasePlugin(_make_fresh())
        plugin.import_manufacturer_part = _failing_import.__get__(plugin, _BasePlugin)
        result = plugin._enrich_part(harness.part.pk, dry_run=False)

        assert any("manufacturer_part" in e for e in result["errors"])
        assert "manufacturer_part:link" not in result["updated"]


class TestNormalizeName:
    """Unit tests for the normalize_name utility."""

    def test_strips_whitespace(self):
        assert normalize_name("  TI  ") == "ti"

    def test_collapses_internal_whitespace(self):
        assert normalize_name("Texas   Instruments") == "texasinstruments"

    def test_lowercases(self):
        assert normalize_name("Voltage") == "voltage"

    def test_idempotent(self):
        name = "  Forward   Voltage  (V)  "
        assert normalize_name(name) == normalize_name(normalize_name(name))

    def test_removes_punctuation(self):
        assert normalize_name("TI, Inc.") == "tiinc"

    def test_matches_without_spaces(self):
        assert normalize_name("texasinstruments") == normalize_name("Texas Instruments")


class TestParameterNormalization:
    """Normalization deduplicates parameter templates across whitespace/case variants."""

    def test_service_finds_template_despite_whitespace_variant(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        template = _Template("Voltage", "V")
        result, _ = _run_service(
            monkeypatch,
            runtime,
            fresh=_make_fresh(
                parameters=[PartParameter(name="  Voltage  ", value="5V", units="V")]
            ),
            templates=[template],
        )

        assert "parameter:  Voltage  " in result["updated"]

    def test_service_finds_template_despite_case_variant(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        template = _Template("voltage", "V")
        result, _ = _run_service(
            monkeypatch,
            runtime,
            fresh=_make_fresh(parameters=[PartParameter(name="Voltage", value="5V", units="V")]),
            templates=[template],
        )

        assert "parameter:Voltage" in result["updated"]

    def test_base_finds_template_despite_case_variant(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        template = _Template("voltage", "V")
        result, _ = _run_base(
            monkeypatch,
            runtime,
            fresh=_make_fresh(parameters=[PartParameter(name="Voltage", value="5V", units="V")]),
            templates=[template],
        )

        assert "parameter:Voltage" in result["updated"]

    def test_service_no_duplicate_template_created(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        template = _Template("Voltage", "V")
        harness = _install_backend(
            monkeypatch,
            runtime,
            templates=[template],
        )
        plugin = _ServicePlugin(
            _make_fresh(
                parameters=[PartParameter(name="voltage", value="5V", units="V")],
                extra_data={},
            )
        )
        enrich_module.enrich_part_for_provider(
            plugin,
            "test-provider",
            harness.part.pk,
            dry_run=False,
        )

        # Should reuse existing template, not create a new one
        assert len(harness.template_manager.templates) == 1


class TestCompanyNormalization:
    """Normalization deduplicates manufacturer companies across whitespace/case."""

    def test_service_reuses_company_despite_whitespace(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, harness = _run_service(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
            fresh=_make_fresh(manufacturer_name="  TI  ", manufacturer_part_number="LM358"),
        )

        assert "manufacturer_part:link" in result["updated"]
        assert len(harness.company_manager.companies) == 1

    def test_service_reuses_company_despite_case(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, harness = _run_service(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
            fresh=_make_fresh(manufacturer_name="ti", manufacturer_part_number="LM358"),
        )

        assert "manufacturer_part:link" in result["updated"]
        assert len(harness.company_manager.companies) == 1


class _UserParamRecord(_ParamRecord):
    """Parameter record that tracks updated_by for testing."""

    def __init__(self, template: _Template, model_id: int, value: str):
        super().__init__(template=template, model_id=model_id, value=value)
        self.updated_by = None


class TestUserAttribution:
    """User is set as updated_by on parameter rows when supported."""

    def test_service_sets_updated_by_on_create(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        test_user = SimpleNamespace(username="testuser", pk=99)
        harness = _install_backend(monkeypatch, runtime)
        plugin = _ServicePlugin(_make_fresh())
        result = enrich_module.enrich_part_for_provider(
            plugin,
            "test-provider",
            harness.part.pk,
            dry_run=False,
            user=test_user,
        )

        assert "parameter:Voltage" in result["updated"]

    def test_service_sets_updated_by_on_update(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        test_user = SimpleNamespace(username="testuser", pk=99)
        template = _Template("Voltage", "V")
        param = _UserParamRecord(template=template, model_id=42, value="3V")
        result, _ = _run_service(
            monkeypatch,
            runtime,
            templates=[template],
            parameters=[param],
            user=test_user,
        )

        assert "parameter:Voltage" in result["updated"]
        assert param.updated_by is test_user

    def test_base_sets_updated_by_on_update(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        test_user = SimpleNamespace(username="testuser", pk=99)
        template = _Template("Voltage", "V")
        param = _UserParamRecord(template=template, model_id=42, value="3V")
        result, _ = _run_base(
            monkeypatch,
            runtime,
            templates=[template],
            parameters=[param],
            user=test_user,
        )

        assert "parameter:Voltage" in result["updated"]
        assert param.updated_by is test_user

    def test_no_user_is_safe(self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace):
        template = _Template("Voltage", "V")
        param = _ParamRecord(template=template, model_id=42, value="3V")
        result, _ = _run_service(
            monkeypatch,
            runtime,
            templates=[template],
            parameters=[param],
            user=None,
        )

        assert "parameter:Voltage" in result["updated"]

    def test_supplier_param_gets_user_on_update(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        test_user = SimpleNamespace(username="testuser", pk=99)
        template = _Template("Voltage", "V")
        part_param = _UserParamRecord(template=template, model_id=42, value="3V")
        supplier_param = _UserParamRecord(template=template, model_id=84, value="3V")
        result, _ = _run_service(
            monkeypatch,
            runtime,
            templates=[template],
            parameters=[part_param, supplier_param],
            user=test_user,
        )

        assert "supplier_parameter:Voltage" in result["updated"]
        assert supplier_param.updated_by is test_user


class TestCompanyNormalizationRawStoredRegression:
    """Regression: raw-stored DB names must be matched by normalized lookup.

    The DB stores raw display names like ``"Texas Instruments"``.  The old code did
    ``name__iexact=normalize_name("Texas Instruments")`` which becomes
    ``name__iexact="texasinstruments"`` — that never matches the raw
    ``"Texas Instruments"`` in the DB.  The new helpers iterate all records and
    compare normalized forms in Python.
    """

    def test_service_finds_raw_stored_company(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        result, harness = _run_service(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
            fresh=_make_fresh(
                manufacturer_name="Texas-Instruments",
                manufacturer_part_number="LM358",
            ),
        )

        assert "manufacturer_part:link" in result["updated"]
        assert len(harness.company_manager.companies) == 1
        assert harness.company_manager.companies[0].name == "Texas-Instruments"

    def test_base_finds_raw_stored_company(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        supplier_part = _make_supplier_part()
        supplier_part.manufacturer_part = None
        # Pre-create a company with a raw display name
        harness = _install_backend(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
        )
        harness.company_manager.companies.append(
            _CompanyRecord(name="Texas Instruments", is_manufacturer=True)
        )
        plugin = _BasePlugin(
            _make_fresh(
                manufacturer_name="texasinstruments",
                manufacturer_part_number="LM358",
            )
        )
        result = plugin._enrich_part(
            harness.part.pk,
            dry_run=False,
        )

        assert "manufacturer_part:link" in result["updated"]
        assert len(harness.company_manager.companies) == 1

    def test_service_finds_raw_stored_template(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        # Pre-create a template with a unmatched raw name
        template = _Template("Forward Voltage (V)", "V")
        result, harness = _run_service(
            monkeypatch,
            runtime,
            fresh=_make_fresh(
                parameters=[PartParameter(name="forward voltage (V)", value="5V", units="V")],
                extra_data={},
            ),
            templates=[template],
        )

        assert "parameter:forward voltage (V)" in result["updated"]
        assert len(harness.template_manager.templates) == 1

    def test_base_finds_raw_stored_template(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        template = _Template("Forward Voltage (V)", "V")
        result, harness = _run_base(
            monkeypatch,
            runtime,
            fresh=_make_fresh(
                parameters=[PartParameter(name="forward voltage (V)", value="5V", units="V")],
                extra_data={},
            ),
            templates=[template],
        )

        assert "parameter:forward voltage (V)" in result["updated"]
        assert len(harness.template_manager.templates) == 1


class TestSupplierStockAvailability:
    """Supplier stock updates SupplierPart availability only."""

    def test_service_updates_supplier_availability(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        result, harness = _run_service(monkeypatch, runtime)

        assert "supplier_part:available" in result["updated"]
        assert "parameter:Supplier Stock" not in result["updated"]
        assert "supplier_parameter:Supplier Stock" not in result["updated"]
        harness.supplier_part.update_available_quantity.assert_called_once_with(100)

    def test_base_updates_supplier_availability(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        result, harness = _run_base(monkeypatch, runtime)

        assert "supplier_part:available" in result["updated"]
        assert "parameter:Supplier Stock" not in result["updated"]
        assert "supplier_parameter:Supplier Stock" not in result["updated"]
        harness.supplier_part.update_available_quantity.assert_called_once_with(100)

    def test_not_created_when_no_stock(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        result, _ = _run_service(monkeypatch, runtime, fresh=_make_fresh(extra_data={}))

        assert "supplier_part:available" not in result["updated"]
        assert "supplier_part:available" not in result["skipped"]

    def test_zero_stock_updates_existing_supplier_available(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        supplier_part = _make_supplier_part(available=25)
        supplier_part.update_available_quantity = MagicMock()
        result, _ = _run_service(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
            fresh=_make_fresh(extra_data={"stock": 0}),
        )

        assert "supplier_part:available" in result["updated"]
        assert "supplier_parameter:Supplier Stock" not in result["updated"]
        supplier_part.update_available_quantity.assert_called_once_with(0)

    def test_skipped_when_supplier_stock_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        supplier_part = _make_supplier_part(available=100)
        supplier_part.update_available_quantity = MagicMock()
        result, _ = _run_service(
            monkeypatch,
            runtime,
            supplier_part=supplier_part,
            fresh=_make_fresh(extra_data={"stock": 100}),
        )

        assert "supplier_part:available" not in result["updated"]
        assert "supplier_part:available" not in result["skipped"]
        supplier_part.update_available_quantity.assert_not_called()

    def test_preview_diff_uses_supplier_part_available_only(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        result, _ = _run_service(monkeypatch, runtime, dry_run=True)

        diff = result["diff"]
        available_rows = [r for r in diff["supplier_part"] if r["field"] == "available"]
        assert len(available_rows) == 1
        assert available_rows[0]["incoming"] == 100
        assert "supplier_parameters" not in diff

    def test_preview_diff_includes_zero_supplier_stock(
        self, monkeypatch: pytest.MonkeyPatch, runtime: SimpleNamespace
    ):
        result, _ = _run_service(
            monkeypatch,
            runtime,
            dry_run=True,
            fresh=_make_fresh(extra_data={"stock": 0}),
        )

        diff = result["diff"]
        available_rows = [r for r in diff["supplier_part"] if r["field"] == "available"]
        assert len(available_rows) == 1
        assert available_rows[0]["incoming"] == 0
