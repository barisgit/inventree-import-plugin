from __future__ import annotations

import sys
import types
from contextlib import nullcontext
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Sequence
from unittest.mock import MagicMock

import json

import pytest

import inventree_import_plugin.base as base_module
import inventree_import_plugin.services.enrich as enrich_module
from inventree_import_plugin.base import BaseImportPlugin
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
        self.templates = {template.name: template for template in templates or []}

    def filter(self, **kwargs):
        name = kwargs.get("name")
        template = self.templates.get(name) if isinstance(name, str) else None
        return _Query([] if template is None else [template])

    def get_or_create(self, name: str, defaults: dict[str, str]):
        template = self.templates.get(name)
        if template is not None:
            return template, False
        template = _Template(name=name, units=defaults.get("units", ""))
        self.templates[name] = template
        return template, True


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


@dataclass
class _Harness:
    part: MagicMock
    supplier_part: MagicMock
    price_break_manager: _PriceBreakManager
    attachment_manager: _AttachmentManager
    template_manager: _TemplateManager
    parameter_manager: _ParamManager
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
    result = plugin._enrich_part(harness.part.pk, dry_run=dry_run)
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

        def _fake_enrich(_plugin, provider_slug, part_id, *, dry_run, selected_keys=None):
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
