from datetime import datetime
import re
from typing import Any, Dict, Optional

from pydantic.utils import to_camel

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def to_js_time(dt) -> Optional[int]:
    """Converts Python datetime to Javascript timestamp"""
    if dt is None:
        return None

    return int(dt.timestamp() * 1000)


def to_ms(duration) -> Optional[int]:
    """Converts python timedelta to Milliseconds"""
    if duration is None:
        return None

    return int(duration.total_seconds() * 1000)


def to_s(duration) -> Optional[int]:
    """Converts python timedelta to Milliseconds"""
    if duration is None:
        return None

    return int(duration.total_seconds())


def from_js_time(num) -> datetime:
    """Converts Javascript timestamp to Python datetime"""
    return datetime.fromtimestamp(int(num) / 1000)


def process_datetime(data: Dict[str, Any], key: str) -> Optional[datetime]:
    """Extracts datetime object from Protect dictionary"""
    return None if data[key] is None else from_js_time(data[key])


def format_datetime(dt: Optional[datetime], default: Optional[str] = None):
    """Formats a datetime object in a consisent format"""
    return default if dt is None else dt.strftime(DATETIME_FORMAT)


def is_online(data: Dict[str, Any]):
    return data["state"] == "CONNECTED"


def is_doorbell(data: Dict[str, Any]):
    return "doorbell" in str(data["type"]).lower()


def to_snake_case(name):
    name = re.sub("(.)([A-Z0-9][a-z]+)", r"\1_\2", name)
    name = re.sub("__([A-Z])", r"_\1", name)
    name = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.lower()


def to_camel_case(name):
    name = to_camel(name)
    return name[0].lower() + name[1:]


def to_camel_case_dict(data):
    for key in list(data.keys()):
        value = data.pop(key)
        if isinstance(value, dict):
            value = to_camel_case_dict(value)

        data[to_camel_case(key)] = value

    return data
