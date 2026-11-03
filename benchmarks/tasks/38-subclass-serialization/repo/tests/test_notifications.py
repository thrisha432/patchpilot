from app.notifications import EmailChannel, SmsChannel, Subscription, export


def test_export_keeps_channel_details():
    sub = Subscription(user="ada", channels=[EmailChannel(address="a@x.io"), SmsChannel(number="+47 1")])
    assert export(sub) == {
        "user": "ada",
        "channels": [{"kind": "email", "address": "a@x.io"}, {"kind": "sms", "number": "+47 1"}],
    }
