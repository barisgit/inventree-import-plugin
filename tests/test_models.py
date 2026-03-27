"""Tests for the core data models."""

from inventree_import_plugin.models import PartData, PartParameter, PriceBreak


class TestPriceBreak:
    def test_fields(self) -> None:
        pb = PriceBreak(quantity=10, price=1.25, currency="USD")
        assert pb.quantity == 10
        assert pb.price == 1.25
        assert pb.currency == "USD"

    def test_currency_default(self) -> None:
        pb = PriceBreak(quantity=1, price=2.50)
        assert pb.currency == "EUR"


class TestPartParameter:
    def test_defaults(self) -> None:
        pp = PartParameter(name="Voltage", value="5V")
        assert pp.units == ""

    def test_with_units(self) -> None:
        pp = PartParameter(name="Resistance", value="10", units="kOhm")
        assert pp.units == "kOhm"


class TestPartData:
    def test_required_fields(self) -> None:
        pd = PartData(sku="SKU-001", name="Test Part", description="A test part")
        assert pd.sku == "SKU-001"
        assert pd.name == "Test Part"
        assert pd.description == "A test part"
        assert pd.manufacturer_name == ""
        assert pd.manufacturer_part_number == ""
        assert pd.link == ""
        assert pd.image_url == ""
        assert pd.datasheet_url == ""
        assert pd.price_breaks == []
        assert pd.parameters == []
        assert pd.extra_data == {}

    def test_list_fields_are_independent(self) -> None:
        pd1 = PartData(sku="A", name="Part A", description="First")
        pd2 = PartData(sku="B", name="Part B", description="Second")
        pd1.price_breaks.append(PriceBreak(quantity=1, price=1.0))
        assert pd2.price_breaks == []

    def test_with_nested_data(self) -> None:
        pd = PartData(
            sku="SKU-002",
            name="Full Part",
            description="Full part",
            manufacturer_name="ACME",
            manufacturer_part_number="MPN-002",
            parameters=[PartParameter(name="V", value="3.3", units="V")],
            price_breaks=[PriceBreak(quantity=1, price=2.50, currency="EUR")],
            extra_data={"category": "Capacitor"},
        )
        assert len(pd.parameters) == 1
        assert len(pd.price_breaks) == 1
        assert pd.extra_data["category"] == "Capacitor"
