from app.events import Click, Scroll, parse_events


def test_dispatch_by_type():
    events = parse_events([{"type": "scroll", "delta": 3}, {"type": "click", "x": 1, "y": 2}])
    assert isinstance(events[0], Scroll) and isinstance(events[1], Click)
