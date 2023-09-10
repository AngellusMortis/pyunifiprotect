from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from decimal import Decimal
from enum import Enum
from inspect import isclass
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Union,
)
from uuid import UUID


from pyunifiprotect.data import ProtectBaseObject, ProtectModel
from pyunifiprotect.data.types import (
    Color,
    Version,
)
from .utils import from_js_time, to_js_time, to_ms

try:
    from pydantic.v1.fields import SHAPE_DICT, SHAPE_LIST, SHAPE_SET, ModelField
    from pydantic.v1.utils import to_camel
except ImportError:
    from pydantic.fields import (  # type: ignore
        SHAPE_DICT,
        SHAPE_LIST,
        SHAPE_SET,
        ModelField,
    )
    from pydantic.utils import to_camel  # type: ignore


SNAKE_CASE_KEYS = [
    "life_span",
    "bad_sector",
    "total_bytes",
    "used_bytes",
    "space_type",
]
_CREATE_TYPES = {IPv6Address, IPv4Address, UUID, Color, Decimal, Path, Version}

IP_TYPES = {
    Union[IPv4Address, str, None],
    Union[IPv4Address, str],
    Union[IPv6Address, str, None],
    Union[IPv6Address, str],
    Union[IPv6Address, IPv4Address, str, None],
    Union[IPv6Address, IPv4Address, str],
    Union[IPv6Address, IPv4Address],
    Union[IPv6Address, IPv4Address, None],
}


def convert_unifi_data(value: Any, field: ModelField) -> Any:
    """Converts value from UFP data into pydantic field class"""

    shape = field.shape
    type_ = field.type_

    if type_ == Any:
        return value

    if shape == SHAPE_LIST and isinstance(value, list):
        value = [convert_unifi_data(v, field) for v in value]
    elif shape == SHAPE_SET and isinstance(value, list):
        value = {convert_unifi_data(v, field) for v in value}
    elif shape == SHAPE_DICT and isinstance(value, dict):
        value = {k: convert_unifi_data(v, field) for k, v in value.items()}
    elif type_ in IP_TYPES and value is not None:
        try:
            value = ip_address(value)
        except ValueError:
            pass
    elif value is None or not isclass(type_) or issubclass(type_, ProtectBaseObject) or isinstance(value, type_):
        return value
    elif type_ in _CREATE_TYPES or issubclass(type_, Enum):
        value = type_(value)
    elif type_ == datetime:
        value = from_js_time(value)

    return value


def serialize_unifi_obj(value: Any) -> Any:
    """Serializes UFP data"""
    if isinstance(value, ProtectModel):
        value = value.unifi_dict()
    if isinstance(value, dict):
        value = serialize_dict(value)
    elif isinstance(value, Iterable) and not isinstance(value, str):
        value = serialize_list(value)
    elif isinstance(value, Enum):
        value = value.value
    elif isinstance(value, (IPv4Address, IPv6Address, UUID, Path, tzinfo, Version)):
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
        set_key = key
        if set_key not in SNAKE_CASE_KEYS:
            set_key = to_camel_case(set_key)
        data[set_key] = serialize_unifi_obj(data.pop(key))

    return data


def serialize_list(items: Iterable[Any]) -> List[Any]:
    """Serializes UFP data list"""
    new_items: List[Any] = []
    for item in items:
        new_items.append(serialize_unifi_obj(item))

    return new_items


def to_camel_case(name: str) -> str:
    """Converts string to camelCase"""
    # repeated runs through should not keep lowercasing
    if "_" in name:
        name = to_camel(name)
        return name[0].lower() + name[1:]
    return name
