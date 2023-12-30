from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable, Coroutine, Iterable
import contextlib
from copy import deepcopy
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from hashlib import sha224
from http.cookies import Morsel
from inspect import isclass
from ipaddress import IPv4Address, IPv6Address, ip_address
import json
import logging
import math
import os
from pathlib import Path
import re
import socket
import sys
import time
from typing import TYPE_CHECKING, Any, Optional, Union, overload
from uuid import UUID
import zoneinfo

from aiohttp import ClientResponse
import jwt

from pyunifiprotect.data.types import (
    Color,
    SmartDetectAudioType,
    SmartDetectObjectType,
    Version,
    VideoMode,
)
from pyunifiprotect.exceptions import NvrError

try:
    from pydantic.v1.fields import SHAPE_DICT, SHAPE_LIST, SHAPE_SET, ModelField
    from pydantic.v1.utils import to_camel
except ImportError:
    from pydantic.fields import (  # type: ignore[attr-defined]
        SHAPE_DICT,
        SHAPE_LIST,
        SHAPE_SET,
        ModelField,
    )
    from pydantic.utils import to_camel

if TYPE_CHECKING:
    from pyunifiprotect.api import ProtectApiClient
    from pyunifiprotect.data import CoordType
    from pyunifiprotect.data.bootstrap import WSStat

if sys.version_info[:2] < (3, 11):
    from async_timeout import timeout as asyncio_timeout
else:
    from asyncio import timeout as asyncio_timeout  # noqa: F401

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DEBUG_ENV = "UFP_DEBUG"
PROGRESS_CALLABLE = Callable[[int, str], Coroutine[Any, Any, None]]
SNAKE_CASE_KEYS = [
    "life_span",
    "bad_sector",
    "total_bytes",
    "used_bytes",
    "space_type",
]
TIMEZONE_GLOBAL: tzinfo | None = None

SNAKE_CASE_MATCH_1 = re.compile("(.)([A-Z0-9][a-z]+)")
SNAKE_CASE_MATCH_2 = re.compile("__([A-Z0-9])")
SNAKE_CASE_MATCH_3 = re.compile("([a-z0-9])([A-Z])")

_LOGGER = logging.getLogger(__name__)

RELEASE_CACHE = Path(__file__).parent / "release_cache.json"

_CREATE_TYPES = {IPv6Address, IPv4Address, UUID, Color, Decimal, Path, Version}
_BAD_UUID = "00000000-0000-00 0- 000-000000000000"

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

if sys.version_info[:2] < (3, 11):
    pass
else:
    pass


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
        data = await response.json()
        reason = data.get("error", str(data))
    except Exception:
        with contextlib.suppress(Exception):
            reason = await response.text()

    return reason


@overload
def to_js_time(dt: datetime | int) -> int:
    ...


@overload
def to_js_time(dt: None) -> None:
    ...


def to_js_time(dt: datetime | int | None) -> Optional[int]:
    """Converts Python datetime to Javascript timestamp"""

    if dt is None:
        return None

    if isinstance(dt, int):
        return dt

    if dt.tzinfo is None:
        return int(time.mktime(dt.timetuple()) * 1000)

    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def to_ms(duration: Optional[timedelta]) -> Optional[int]:
    """Converts python timedelta to Milliseconds"""

    if duration is None:
        return None

    return int(round(duration.total_seconds() * 1000))


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def from_js_time(num: Union[float, str, datetime]) -> datetime:
    """Converts Javascript timestamp to Python datetime"""

    if isinstance(num, datetime):
        return num

    return datetime.fromtimestamp(int(num) / 1000, tz=timezone.utc)


def process_datetime(data: dict[str, Any], key: str) -> Optional[datetime]:
    """Extracts datetime object from Protect dictionary"""

    return None if data.get(key) is None else from_js_time(data[key])


def format_datetime(
    dt: Optional[datetime],
    default: Optional[str] = None,
) -> Optional[str]:
    """Formats a datetime object in a consisent format"""

    return default if dt is None else dt.strftime(DATETIME_FORMAT)


def is_online(data: dict[str, Any]) -> bool:
    return bool(data["state"] == "CONNECTED")


def is_doorbell(data: dict[str, Any]) -> bool:
    return "doorbell" in str(data["type"]).lower()


@lru_cache(maxsize=1024)
def to_snake_case(name: str) -> str:
    """Converts string to snake_case"""
    name = SNAKE_CASE_MATCH_1.sub(r"\1_\2", name)
    name = SNAKE_CASE_MATCH_2.sub(r"_\1", name)
    name = SNAKE_CASE_MATCH_3.sub(r"\1_\2", name)
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

    type_ = field.type_

    if type_ == Any:
        return value

    shape = field.shape
    if shape == SHAPE_LIST and isinstance(value, list):
        return [convert_unifi_data(v, field) for v in value]
    if shape == SHAPE_SET and isinstance(value, list):
        return {convert_unifi_data(v, field) for v in value}
    if shape == SHAPE_DICT and isinstance(value, dict):
        return {k: convert_unifi_data(v, field) for k, v in value.items()}

    if value is not None:
        if type_ in IP_TYPES:
            try:
                return ip_address(value)
            except ValueError:
                return value
        if type_ == datetime:
            return from_js_time(value)
        if type_ in _CREATE_TYPES or (isclass(type_) and issubclass(type_, Enum)):
            # cannot do this check too soon because some types cannot be used in isinstance
            if isinstance(value, type_):
                return value
            # handle edge case for improperly formated UUIDs
            # 00000000-0000-00 0- 000-000000000000
            if type_ == UUID and value == _BAD_UUID:
                value = "0" * 32
            return type_(value)

    return value


def serialize_unifi_obj(value: Any) -> Any:
    """Serializes UFP data"""
    if unifi_dict := getattr(value, "unifi_dict", None):
        value = unifi_dict()

    if isinstance(value, dict):
        return serialize_dict(value)
    if isinstance(value, Iterable) and not isinstance(value, str):
        return serialize_list(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (IPv4Address, IPv6Address, UUID, Path, tzinfo, Version)):
        return str(value)
    if isinstance(value, datetime):
        return to_js_time(value)
    if isinstance(value, timedelta):
        return to_ms(value)
    if isinstance(value, Color):
        return value.as_hex().upper()

    return value


def serialize_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Serializes UFP data dict"""
    for key in list(data.keys()):
        set_key = key
        if set_key not in SNAKE_CASE_KEYS:
            set_key = to_camel_case(set_key)
        data[set_key] = serialize_unifi_obj(data.pop(key))

    return data


def serialize_coord(coord: CoordType) -> Union[int, float]:
    """Serializes UFP zone coordinate"""
    from pyunifiprotect.data import Percent

    if not isinstance(coord, Percent):
        return coord

    if math.isclose(coord, 0) or math.isclose(coord, 1):
        return int(coord)
    return coord


def serialize_point(point: tuple[CoordType, CoordType]) -> list[Union[int, float]]:
    """Serializes UFP zone coordinate point"""
    return [
        serialize_coord(point[0]),
        serialize_coord(point[1]),
    ]


def serialize_list(items: Iterable[Any]) -> list[Any]:
    """Serializes UFP data list"""

    return [serialize_unifi_obj(i) for i in items]


def convert_smart_types(items: Iterable[str]) -> list[SmartDetectObjectType]:
    """Converts list of str into SmartDetectObjectType. Any unknown values will be ignored and logged."""

    types = []
    for smart_type in items:
        try:
            types.append(SmartDetectObjectType(smart_type))
        except ValueError:
            _LOGGER.warning("Unknown smart detect type: %s", smart_type)
    return types


def convert_smart_audio_types(items: Iterable[str]) -> list[SmartDetectAudioType]:
    """Converts list of str into SmartDetectAudioType. Any unknown values will be ignored and logged."""

    types = []
    for smart_type in items:
        try:
            types.append(SmartDetectAudioType(smart_type))
        except ValueError:
            _LOGGER.warning("Unknown smart detect audio type: %s", smart_type)
    return types


def convert_video_modes(items: Iterable[str]) -> list[VideoMode]:
    """Converts list of str into VideoMode. Any unknown values will be ignored and logged."""

    types = []
    for video_mode in items:
        try:
            types.append(VideoMode(video_mode))
        except ValueError:
            _LOGGER.warning("Unknown video mode: %s", video_mode)
    return types


def ip_from_host(host: str) -> IPv4Address | IPv6Address:
    try:
        return ip_address(host)
    except ValueError:
        pass

    return ip_address(socket.gethostbyname(host))


def dict_diff(orig: Optional[dict[str, Any]], new: dict[str, Any]) -> dict[str, Any]:
    changed: dict[str, Any] = {}

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
        elif value != orig[key]:
            changed[key] = deepcopy(value)

    return changed


def ws_stat_summmary(
    stats: list[WSStat],
) -> tuple[list[WSStat], float, Counter[str], Counter[str], Counter[str]]:
    if len(stats) == 0:
        raise ValueError("No stats to summarize")

    unfiltered = [s for s in stats if not s.filtered]
    percent = (1 - len(unfiltered) / len(stats)) * 100
    keys = Counter(k for s in unfiltered for k in s.keys_set)
    models = Counter(k.model for k in unfiltered)
    actions = Counter(k.action for k in unfiltered)

    return unfiltered, percent, keys, models, actions


async def write_json(output_path: Path, data: Union[list[Any], dict[str, Any]]) -> None:
    def write() -> None:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            f.write("\n")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, write)


def print_ws_stat_summary(
    stats: list[WSStat],
    output: Optional[Callable[[Any], Any]] = None,
) -> None:
    # typer<0.4.1 is incompatible with click>=8.1.0
    # allows only the CLI interface to break if both are installed
    import typer

    if output is None:
        output = typer.echo if typer is not None else print

    unfiltered, percent, keys, models, actions = ws_stat_summmary(stats)

    title = " ws stat summary "
    side_length = int((80 - len(title)) / 2)

    lines = [
        "-" * side_length + title + "-" * side_length,
        f"packet count: {len(stats)}",
        f"filtered packet count: {len(unfiltered)} ({percent:.4}%)",
        "-" * 80,
    ]

    for key, count in models.most_common():
        lines.append(f"{key}: {count}")
    lines.append("-" * 80)

    for key, count in actions.most_common():
        lines.append(f"{key}: {count}")
    lines.append("-" * 80)

    for key, count in keys.most_common(10):
        lines.append(f"{key}: {count}")
    lines.append("-" * 80)

    output("\n".join(lines))


async def profile_ws(
    protect: ProtectApiClient,
    duration: int,
    output_path: Optional[Path] = None,
    ws_progress: Optional[PROGRESS_CALLABLE] = None,
    do_print: bool = True,
    print_output: Optional[Callable[[Any], Any]] = None,
) -> None:
    if protect.bootstrap.capture_ws_stats:
        raise NvrError("Profile already in progress")

    _LOGGER.debug("Starting profile...")
    protect.bootstrap.clear_ws_stats()
    protect.bootstrap.capture_ws_stats = True

    if ws_progress is not None:
        await ws_progress(duration, "Waiting for WS messages")
    else:
        await asyncio.sleep(duration)

    protect.bootstrap.capture_ws_stats = False
    _LOGGER.debug("Finished profile...")

    if output_path:
        json_data = [s.__dict__ for s in protect.bootstrap.ws_stats]
        await write_json(output_path, json_data)

    if do_print:
        print_ws_stat_summary(protect.bootstrap.ws_stats, output=print_output)


def decode_token_cookie(token_cookie: Morsel[str]) -> dict[str, Any] | None:
    """Decode a token cookie if it is still valid."""
    try:
        return jwt.decode(
            token_cookie.value,
            options={"verify_signature": False, "verify_exp": True},
        )
    except jwt.ExpiredSignatureError:
        _LOGGER.debug("Authentication token has expired.")
        return None
    except Exception as broad_ex:
        _LOGGER.debug("Authentication token decode error: %s", broad_ex)
        return None


def format_duration(duration: timedelta) -> str:
    """Formats a timedelta as a string."""

    seconds = int(duration.total_seconds())
    hours = seconds // 3600
    seconds -= hours * 3600
    minutes = seconds // 60
    seconds -= minutes * 60

    output = ""
    if hours > 0:
        output = f"{hours}h"
    if minutes > 0:
        output = f"{output}{minutes}m"
    return f"{output}{seconds}s"


def _set_timezone(tz: tzinfo | str) -> tzinfo:
    global TIMEZONE_GLOBAL  # noqa: PLW0603

    if isinstance(tz, str):
        tz = zoneinfo.ZoneInfo(tz)

    TIMEZONE_GLOBAL = tz

    return TIMEZONE_GLOBAL


def get_local_timezone() -> tzinfo:
    """Gets Olson timezone name for localizing datetimes"""

    if TIMEZONE_GLOBAL is not None:
        return TIMEZONE_GLOBAL

    try:
        from homeassistant.util import dt as dt_util  # type: ignore[import-not-found]

        return _set_timezone(dt_util.DEFAULT_TIME_ZONE)
    except ImportError:
        pass

    timezone_name = os.environ.get("TZ")
    if timezone_name:
        return _set_timezone(timezone_name)

    timezone_name = "UTC"
    timezone_locale = Path("/etc/localtime")
    if timezone_locale.exists():
        tzfile_digest = sha224(Path(timezone_locale).read_bytes()).hexdigest()

        for root, _, filenames in os.walk(Path("/usr/share/zoneinfo/")):
            for filename in filenames:
                fullname = os.path.join(root, filename)
                digest = sha224(Path(fullname).read_bytes()).hexdigest()
                if digest == tzfile_digest:
                    timezone_name = "/".join((fullname.split("/"))[-2:])

    return _set_timezone(timezone_name)


def local_datetime(dt: datetime | None = None) -> datetime:
    """Returns datetime in local timezone"""

    if dt is None:
        dt = datetime.now(tz=timezone.utc)

    local_tz = get_local_timezone()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=local_tz)
    return dt.astimezone(local_tz)
