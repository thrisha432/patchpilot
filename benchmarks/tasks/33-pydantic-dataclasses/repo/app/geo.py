from pydantic.dataclasses import dataclass


class StrictConfig:
    anystr_strip_whitespace = True
    validate_assignment = True


@dataclass(config=StrictConfig)
class Point:
    label: str
    lat: float
    lon: float

    def __post_init_post_parse__(self):
        if not (-90 <= self.lat <= 90 and -180 <= self.lon <= 180):
            raise ValueError("coordinates out of range")
        self.label = self.label.title()


def make_point(label, lat, lon) -> Point:
    return Point(label=label, lat=lat, lon=lon)
