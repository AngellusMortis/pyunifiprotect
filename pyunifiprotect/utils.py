import contextlib
from datetime import datetime
from typing import Any, Dict, Optional

from aiohttp import ClientResponse

from pyunifiprotect.unifi_data import StateType

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


async def get_response_reason(response: ClientResponse) -> str:
    reason = str(response.reason)

    try:
        json = await response.json()
        reason = json.get("error", str(json))
    except Exception:  # pylint: disable=broad-except
        with contextlib.suppress(Exception):
            reason = await response.text()

    return reason


def to_js_time(dt) -> int:
    """Converts Python datetime to Javascript timestamp"""
    return int(dt.timestamp() * 1000)


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
    return data["state"] == StateType.CONNECTED.value


def is_doorbell(data: Dict[str, Any]):
    return "doorbell" in str(data["type"]).lower()
