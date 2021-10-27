import asyncio
import base64
from datetime import datetime
import json
import os
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from pyunifiprotect import ProtectApiClient, UpvServer
from pyunifiprotect.data import ModelType
from tests.sample_data.constants import CONSTANTS

UFP_SAMPLE_DIR = os.environ.get("UFP_SAMPLE_DIR")
if UFP_SAMPLE_DIR:
    SAMPLE_DATA_DIRECTORY = Path(UFP_SAMPLE_DIR)
else:
    SAMPLE_DATA_DIRECTORY = Path(__file__).parent / "sample_data"


def read_binary_file(name: str, ext: str = "png"):
    with open(SAMPLE_DATA_DIRECTORY / f"{name}.{ext}", "rb") as f:
        return f.read()


def read_json_file(name: str):
    with open(SAMPLE_DATA_DIRECTORY / f"{name}.json") as f:
        return json.load(f)


def get_now():
    return datetime.fromisoformat(CONSTANTS["time"]).replace(microsecond=0)


async def mock_api_request(path: str, raw: bool = False, *args, **kwargs):

    if raw:
        if path.startswith("thumbnails/"):
            return read_binary_file("sample_camera_thumbnail")
        elif path.startswith("cameras/"):
            return read_binary_file("sample_camera_snapshot")
        return b""

    if path == "bootstrap":
        return read_json_file("sample_bootstrap")
    elif path == "events":
        return read_json_file("sample_raw_events")
    elif path == "liveviews":
        return read_json_file("sample_liveviews")

    return {}


class MockWebsocket:
    is_closed: bool = False
    now: float = 0
    events: List[dict]
    count = 0

    def __init__(self):
        self.events = read_json_file("sample_ws_messages")

    async def close(self):
        self.is_closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if len(self.events) == 0 or self.is_closed:
            raise StopAsyncIteration

        key = list(self.events.keys())[0]
        next_time = float(key)
        await asyncio.sleep(next_time - self.now)
        self.now = next_time

        data = self.events.pop(key)
        self.count += 1
        return aiohttp.WSMessage(aiohttp.WSMsgType.BINARY, base64.b64decode(data["raw"]), None)


MockDatetime = Mock()
MockDatetime.now.return_value = get_now()


@pytest.fixture
@pytest.mark.asyncio
async def old_protect_client():
    client = UpvServer(None, "127.0.0.1", 0, "username", "password")
    client.api_request = AsyncMock(side_effect=mock_api_request)
    client.ensure_authenticated = AsyncMock()
    client.ws_session = AsyncMock()
    client.ws_session.ws_connect = AsyncMock(return_value=MockWebsocket())

    await client.update(True)

    yield client

    await client.async_disconnect_ws()
    await client.req.close()

    if client.ws_task is not None:
        client.ws_task.cancel()

    # empty out websockets
    while client.ws_connection is not None and not client.ws_task.done():
        await asyncio.sleep(0.1)


@pytest.fixture
@pytest.mark.asyncio
async def protect_client():
    client = ProtectApiClient("127.0.0.1", 0, "username", "password")
    client.is_unifi_os = False
    client.api_request = AsyncMock(side_effect=mock_api_request)
    client.ensure_authenticated = AsyncMock()

    await client.update(True)

    yield client


@pytest.fixture
@pytest.mark.asyncio
async def protect_client_ws():
    client = ProtectApiClient("127.0.0.1", 0, "username", "password")
    client.is_unifi_os = True
    client.api_request = AsyncMock(side_effect=mock_api_request)
    client.ensure_authenticated = AsyncMock()
    client.ws_session = AsyncMock()
    client.ws_session.ws_connect = AsyncMock(return_value=MockWebsocket())

    await client.update(True)

    yield client

    await client.async_disconnect_ws()
    await client.req.close()

    if client.ws_task is not None:
        client.ws_task.cancel()

    # empty out websockets
    while client.ws_connection is not None and not client.ws_task.done():
        await asyncio.sleep(0.1)


@pytest.fixture
def liveviews():
    return read_json_file("sample_liveviews")


@pytest.fixture
def viewport():
    return read_json_file("sample_viewport")


@pytest.fixture
def light():
    return read_json_file("sample_light")


@pytest.fixture
def camera():
    return read_json_file("sample_camera")


@pytest.fixture
def ws_messages():
    return read_json_file("sample_ws_messages")


@pytest.fixture
def raw_events():
    return read_json_file("sample_raw_events")


@pytest.fixture
def bootstrap():
    return read_json_file("sample_bootstrap")


@pytest.fixture
def now():
    return get_now()


def compare_objs(obj_type, expected, actual):
    # TODO: fields not supported yet
    if obj_type == ModelType.CAMERA.value:
        del expected["apMac"]
        del expected["apRssi"]
        del expected["elementInfo"]
        del expected["lastPrivacyZonePositionId"]
        del expected["recordingSchedules"]
        del expected["smartDetectLines"]
        del expected["lenses"]
        del expected["featureFlags"]["mountPositions"]
        del expected["featureFlags"]["focus"]
        del expected["featureFlags"]["pan"]
        del expected["featureFlags"]["tilt"]
        del expected["featureFlags"]["zoom"]
        del expected["ispSettings"]["mountPosition"]
    elif obj_type == ModelType.USER.value:
        del expected["settings"]
        del expected["alertRules"]
        del expected["notificationsV2"]
        if expected["cloudAccount"] is not None:
            del expected["cloudAccount"]["profileImg"]
    elif obj_type == ModelType.EVENT.value:
        del expected["metadata"]
        del expected["partition"]

    # sometimes uptime comes back as a str...
    if "uptime" in expected:
        expected["uptime"] = int(expected["uptime"])

    assert expected == actual
