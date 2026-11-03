import json

from app.camel import Shipment, from_wire, to_wire


def test_round_trip_in_camel_case():
    s = Shipment(tracking_number="T1", weight_kg=2.5)
    wire = json.loads(to_wire(s))
    assert wire == {"trackingNumber": "T1", "weightKg": 2.5, "isExpress": False}
    assert from_wire(json.dumps(wire)) == s
