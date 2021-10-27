import contextlib
from datetime import datetime, timedelta, tzinfo
from decimal import Decimal
from enum import Enum
from ipaddress import IPv4Address
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from uuid import UUID

from aiohttp import ClientResponse
from pydantic.color import Color
from pydantic.utils import to_camel

from pyunifiprotect.data.types import Percent

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
CoordType = Union[Percent, int, float]


async def get_response_reason(response: ClientResponse) -> str:
    reason = str(response.reason)

    try:
        json = await response.json()
        reason = json.get("error", str(json))
    except Exception:  # pylint: disable=broad-except
        with contextlib.suppress(Exception):
            reason = await response.text()

    return reason


def to_js_time(dt: Optional[datetime]) -> Optional[int]:
    """Converts Python datetime to Javascript timestamp"""

    if dt is None:
        return None

    return int(dt.timestamp() * 1000)


def to_ms(duration: Optional[timedelta]) -> Optional[int]:
    """Converts python timedelta to Milliseconds"""

    if duration is None:
        return None

    return int(round(duration.total_seconds() * 1000))


def from_js_time(num: Union[int, float, str, datetime]) -> datetime:
    """Converts Javascript timestamp to Python datetime"""

    if isinstance(num, datetime):
        return num

    return datetime.fromtimestamp(int(num) / 1000)


def process_datetime(data: Dict[str, Any], key: str) -> Optional[datetime]:
    """Extracts datetime object from Protect dictionary"""

    return None if data[key] is None else from_js_time(data[key])


def format_datetime(dt: Optional[datetime], default: Optional[str] = None) -> Optional[str]:
    """Formats a datetime object in a consisent format"""

    return default if dt is None else dt.strftime(DATETIME_FORMAT)


def is_online(data: Dict[str, Any]) -> bool:

    return data["state"] == "CONNECTED"


def is_doorbell(data: Dict[str, Any]) -> bool:

    return "doorbell" in str(data["type"]).lower()


def to_snake_case(name: str) -> str:
    name = re.sub("(.)([A-Z0-9][a-z]+)", r"\1_\2", name)
    name = re.sub("__([A-Z0-9])", r"_\1", name)
    name = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.lower()


def to_camel_case(name: str) -> str:
    # repeated runs through should not keep lowercasing
    if "_" in name:
        name = to_camel(name)
        return name[0].lower() + name[1:]
    return name


def serialize_unifi_obj(value: Any) -> Any:
    from pyunifiprotect.data.base import (  # pylint: disable=import-outside-toplevel
        ProtectModel,
    )

    if isinstance(value, ProtectModel):
        value = value.unifi_dict()
    if isinstance(value, dict):
        value = serialize_dict(value)
    elif isinstance(value, Iterable) and not isinstance(value, str):
        value = serialize_list(value)
    elif isinstance(value, Enum):
        value = value.value
    elif isinstance(value, (IPv4Address, UUID, Path, tzinfo)):
        value = str(value)
    elif isinstance(value, datetime):
        value = to_js_time(value)
    elif isinstance(value, timedelta):
        value = to_ms(value)
    elif isinstance(value, Color):
        value = value.as_hex().upper()

    return value


def serialize_dict(data: Dict[str, Any]):
    for key in list(data.keys()):
        data[to_camel_case(key)] = serialize_unifi_obj(data.pop(key))

    return data


def serialize_coord(coord: CoordType) -> Union[int, float]:
    if not isinstance(coord, (Percent, Decimal)):
        return coord

    if coord in (Decimal(1), Decimal(0)):
        return int(coord)
    return float(coord)


def serialize_point(point: Tuple[CoordType, CoordType]) -> List[Union[int, float]]:
    return [
        serialize_coord(point[0]),
        serialize_coord(point[1]),
    ]


def serialize_list(items: Iterable[Any]) -> List[Any]:
    new_items: List[Any] = []
    for item in items:
        new_items.append(serialize_unifi_obj(item))

    return new_items
