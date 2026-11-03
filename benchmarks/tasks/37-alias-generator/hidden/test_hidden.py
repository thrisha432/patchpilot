from app.camel import Shipment


def test_populate_by_field_name_and_alias():
    assert Shipment(trackingNumber="A", weightKg=1) == Shipment(tracking_number="A", weight_kg=1)
