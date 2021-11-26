from __future__ import annotations

import contextlib
from copy import deepcopy
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from enum import Enum
from inspect import isclass
from ipaddress import AddressValueError, IPv4Address
import os
from pathlib import Path
import re
import socket
import time
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple, Union
from uuid import UUID

from aiohttp import ClientResponse
from pydantic.fields import SHAPE_DICT, SHAPE_LIST, ModelField
from pydantic.utils import to_camel

from pyunifiprotect.data.types import Version

if TYPE_CHECKING:
    from pyunifiprotect.data import CoordType

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DEBUG_ENV = "UFP_DEBUG"


def set_debug() -> None:
    """Sets ENV variable for UFP_DEBUG to on (True)"""
    os.environ[DEBUG_ENV] = str(True)


def set_no_debug() -> None:
    """Sets ENV variable for UFP_DEBUG to off (False)"""
    os.environ[DEBUG_ENV] = str(False)


def is_debug() -> bool:
    """Returns if debug ENV is on (True)"""
    return os.environ.get(DEBUG_ENV) == str(True)


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

    if dt.tzinfo is None:
        return int(time.mktime(dt.timetuple()) * 1000)

    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def to_ms(duration: Optional[timedelta]) -> Optional[int]:
    """Converts python timedelta to Milliseconds"""

    if duration is None:
        return None

    return int(round(duration.total_seconds() * 1000))


def utc_now() -> datetime:
    return datetime.utcnow().replace(tzinfo=timezone.utc)


def from_js_time(num: Union[int, float, str, datetime]) -> datetime:
    """Converts Javascript timestamp to Python datetime"""

    if isinstance(num, datetime):
        return num

    return datetime.fromtimestamp(int(num) / 1000, tz=timezone.utc)


def process_datetime(data: Dict[str, Any], key: str) -> Optional[datetime]:
    """Extracts datetime object from Protect dictionary"""

    return None if data[key] is None else from_js_time(data[key])


def format_datetime(dt: Optional[datetime], default: Optional[str] = None) -> Optional[str]:
    """Formats a datetime object in a consisent format"""

    return default if dt is None else dt.strftime(DATETIME_FORMAT)


def is_online(data: Dict[str, Any]) -> bool:
    return bool(data["state"] == "CONNECTED")


def is_doorbell(data: Dict[str, Any]) -> bool:
    return "doorbell" in str(data["type"]).lower()


def to_snake_case(name: str) -> str:
    """Converts string to snake_case"""
    name = re.sub("(.)([A-Z0-9][a-z]+)", r"\1_\2", name)
    name = re.sub("__([A-Z0-9])", r"_\1", name)
    name = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name)
    return name.lower()


def to_camel_case(name: str) -> str:
    """Converts string to camelCase"""
    # repeated runs through should not keep lowercasing
    if "_" in name:
        name = to_camel(name)
        return name[0].lower() + name[1:]
    return name


def convert_unifi_data(value: Any, field: ModelField) -> Any:
    """Converts value from UFP data into pydantic field class"""
    from pyunifiprotect.data import (  # pylint: disable=import-outside-toplevel
        Color,
        ProtectBaseObject,
    )

    if (
        value is None
        or not isclass(field.type_)
        or issubclass(field.type_, ProtectBaseObject)
        or isinstance(value, field.type_)
    ):
        return value

    if field.shape == SHAPE_LIST and isinstance(value, list):
        value = [convert_unifi_data(v, field) for v in value]
    elif field.shape == SHAPE_DICT and isinstance(value, dict):
        value = {k: convert_unifi_data(v, field) for k, v in value.items()}
    elif field.type_ == IPv4Address:
        value = IPv4Address(value)
    elif field.type_ == UUID:
        value = UUID(value)
    elif field.type_ == datetime:
        value = from_js_time(value)
    elif field.type_ == Color:
        value = Color(value)
    elif field.type_ == Decimal:
        value = Decimal(value)
    elif field.type_ == Path:
        value = Path(value)
    elif field.type_ == Version:
        value = Version(value)
    elif issubclass(field.type_, Enum):
        value = field.type_(value)

    return value


def serialize_unifi_obj(value: Any) -> Any:
    """Serializes UFP data"""
    from pyunifiprotect.data import (  # pylint: disable=import-outside-toplevel
        Color,
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
    elif isinstance(value, (IPv4Address, UUID, Path, tzinfo, Version)):
        value = str(value)
    elif isinstance(value, datetime):
        value = to_js_time(value)
    elif isinstance(value, timedelta):
        value = to_ms(value)
    elif isinstance(value, Color):
        value = value.as_hex().upper()

    return value


def serialize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Serializes UFP data dict"""
    for key in list(data.keys()):
        data[to_camel_case(key)] = serialize_unifi_obj(data.pop(key))

    return data


def serialize_coord(coord: CoordType) -> Union[int, float]:
    """Serializes UFP zone coordinate"""
    from pyunifiprotect.data import Percent  # pylint: disable=import-outside-toplevel

    if not isinstance(coord, (Percent, Decimal)):
        return coord

    if coord in (Decimal(1), Decimal(0)):
        return int(coord)
    return float(coord)


def serialize_point(point: Tuple[CoordType, CoordType]) -> List[Union[int, float]]:
    """Serializes UFP zone coordinate point"""
    return [
        serialize_coord(point[0]),
        serialize_coord(point[1]),
    ]


def serialize_list(items: Iterable[Any]) -> List[Any]:
    """Serializes UFP data list"""
    new_items: List[Any] = []
    for item in items:
        new_items.append(serialize_unifi_obj(item))

    return new_items


def round_decimal(num: Union[int, float], digits: int) -> Decimal:
    """Rounds a decimal to a set precision"""
    return Decimal(str(round(num, digits)))


def ip_from_host(host: str) -> IPv4Address:
    try:
        return IPv4Address(host)
    except AddressValueError:
        pass

    return IPv4Address(socket.gethostbyname(host))


def dict_diff(orig: Optional[Dict[str, Any]], new: Dict[str, Any]) -> Dict[str, Any]:
    changed: Dict[str, Any] = {}

    if orig is None:
        return new

    for key, value in new.items():
        if key not in orig:
            changed[key] = deepcopy(value)
            continue

        if isinstance(value, dict):
            sub_changed = dict_diff(orig[key], value)

            if sub_changed:
                changed[key] = sub_changed
        else:
            if value != orig[key]:
                changed[key] = deepcopy(value)

    return changed
