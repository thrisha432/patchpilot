from app.notifications import Channel, Subscription, export


def test_plain_channel():
    assert export(Subscription(user="b", channels=[Channel(kind="push")])) == {"user": "b", "channels": [{"kind": "push"}]}
