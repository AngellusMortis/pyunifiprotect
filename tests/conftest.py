import asyncio
import base64
from datetime import datetime
import json
import os
from pathlib import Path
from shlex import split
from subprocess import run
from tempfile import NamedTemporaryFile
from typing import Any, Dict
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from pyunifiprotect import ProtectApiClient, UpvServer
from pyunifiprotect.data import ModelType
from pyunifiprotect.utils import set_debug, set_no_debug
from tests.sample_data.constants import CONSTANTS

UFP_SAMPLE_DIR = os.environ.get("UFP_SAMPLE_DIR")
if UFP_SAMPLE_DIR:
    SAMPLE_DATA_DIRECTORY = Path(UFP_SAMPLE_DIR)
else:
    SAMPLE_DATA_DIRECTORY = Path(__file__).parent / "sample_data"

CHECK_CMD = "ffprobe -v error -select_streams v:0 -show_entries stream=codec_type -of csv=p=0 {filename}"
LENGTH_CMD = "ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {filename}"


def read_binary_file(name: str, ext: str = "png"):
    with open(SAMPLE_DATA_DIRECTORY / f"{name}.{ext}", "rb") as f:
        return f.read()


def read_json_file(name: str):
    with open(SAMPLE_DATA_DIRECTORY / f"{name}.json", encoding="utf8") as f:
        return json.load(f)


def get_now():
    return datetime.fromisoformat(CONSTANTS["time"]).replace(microsecond=0)


def validate_video_file(filepath: Path, length: int):
    output = run(split(CHECK_CMD.format(filename=filepath)), check=True, capture_output=True)
    assert output.stdout.decode("utf8").strip() == "video"

    output = run(split(LENGTH_CMD.format(filename=filepath)), check=True, capture_output=True)
    # it looks like UFP does not always generate a video of exact length
    assert length - 10 < int(float(output.stdout.decode("utf8").strip())) < length + 10


async def mock_api_request_raw(url: str, *args, **kwargs):
    if url.startswith("thumbnails/"):
        return read_binary_file("sample_camera_thumbnail")
    elif url.startswith("cameras/"):
        return read_binary_file("sample_camera_snapshot")
    elif url.startswith("heatmaps/"):
        return read_binary_file("sample_camera_heatmap")
    elif url == "video/export":
        return read_binary_file("sample_camera_video", "mp4")
    return b""


async def mock_api_request(url: str, *args, **kwargs):
    if url == "bootstrap":
        return read_json_file("sample_bootstrap")
    elif url == "events":
        return read_json_file("sample_raw_events")
    elif url == "cameras":
        return [read_json_file("sample_camera")]
    elif url == "lights":
        return [read_json_file("sample_light")]
    elif url == "sensors":
        return [read_json_file("sample_sensor")]
    elif url == "viewers":
        return [read_json_file("sample_viewport")]
    elif url == "bridges":
        return [read_json_file("sample_bridge")]
    elif url == "liveviews":
        return [read_json_file("sample_liveview")]
    elif url.startswith("cameras/"):
        return read_json_file("sample_camera")
    elif url.startswith("lights/"):
        return read_json_file("sample_light")
    elif url.startswith("sensors/"):
        return read_json_file("sample_sensor")
    elif url.startswith("viewers/"):
        return read_json_file("sample_viewport")
    elif url.startswith("bridges/"):
        return read_json_file("sample_bridge")
    elif url.startswith("liveviews/"):
        return read_json_file("sample_liveview")

    return {}


class SimpleMockWebsocket:
    is_closed: bool = False
    now: float = 0
    events: Dict[str, Any]
    count = 0

    def __init__(self):
        self.events = []

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


class MockWebsocket(SimpleMockWebsocket):
    def __init__(self):
        self.events = read_json_file("sample_ws_messages")


MockDatetime = Mock()
MockDatetime.now.return_value = get_now()


@pytest.fixture(autouse=True)
def ensure_debug():
    set_debug()


@pytest.fixture
@pytest.mark.asyncio
async def old_protect_client():
    client = UpvServer(None, "127.0.0.1", 0, "username", "password")
    client.api_request = AsyncMock(side_effect=mock_api_request)
    client.api_request_raw = AsyncMock(side_effect=mock_api_request_raw)
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
    client.api_request = AsyncMock(side_effect=mock_api_request)
    client.api_request_raw = AsyncMock(side_effect=mock_api_request_raw)
    client.ws_session = AsyncMock()
    client.ws_session.ws_connect = AsyncMock(return_value=SimpleMockWebsocket())
    client.ensure_authenticated = AsyncMock()

    await client.update(True)

    yield client

    await client.async_disconnect_ws()
    await client.req.close()

    if client.ws_task is not None:
        client.ws_task.cancel()

    # empty out websockets
    while client.ws_connection is not None and client.ws_task is not None and not client.ws_task.done():
        await asyncio.sleep(0.1)


@pytest.fixture
@pytest.mark.asyncio
async def protect_client_no_debug():
    set_no_debug()

    client = ProtectApiClient("127.0.0.1", 0, "username", "password")
    client.api_request = AsyncMock(side_effect=mock_api_request)
    client.api_request_raw = AsyncMock(side_effect=mock_api_request_raw)
    client.ws_session = AsyncMock()
    client.ws_session.ws_connect = AsyncMock(return_value=SimpleMockWebsocket())
    client.ensure_authenticated = AsyncMock()

    await client.update(True)

    yield client

    await client.async_disconnect_ws()
    await client.req.close()

    if client.ws_task is not None:
        client.ws_task.cancel()

    # empty out websockets
    while client.ws_connection is not None and client.ws_task is not None and not client.ws_task.done():
        await asyncio.sleep(0.1)


@pytest.fixture
@pytest.mark.asyncio
async def protect_client_ws():
    set_no_debug()

    client = ProtectApiClient("127.0.0.1", 0, "username", "password")
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
    while client.ws_connection is not None and client.ws_task is not None and not client.ws_task.done():
        await asyncio.sleep(0.1)


@pytest.fixture
def liveview():
    return read_json_file("sample_liveview")


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
def sensor():
    return read_json_file("sample_sensor")


@pytest.fixture
def bridge():
    return read_json_file("sample_bridge")


@pytest.fixture
def liveviews():
    return [read_json_file("sample_liveview")]


@pytest.fixture
def viewports():
    return [read_json_file("sample_viewport")]


@pytest.fixture
def lights():
    return [read_json_file("sample_light")]


@pytest.fixture
def cameras():
    return [read_json_file("sample_camera")]


@pytest.fixture
def sensors():
    return [read_json_file("sample_sensor")]


@pytest.fixture
def bridges():
    return [read_json_file("sample_bridge")]


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


@pytest.fixture
def tmp_binary_file():
    tmp_file = NamedTemporaryFile(mode="wb", delete=False)

    yield tmp_file

    try:
        tmp_file.close()
    except Exception:  # pylint: disable=broad-except
        pass

    os.remove(tmp_file.name)


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
        if "settings" in expected:
            expected.pop("settings", None)
        del expected["alertRules"]
        del expected["notificationsV2"]
        if expected["cloudAccount"] is not None:
            del expected["cloudAccount"]["profileImg"]
        # lastLoginIp/lastLoginTime is not always present
        if "lastLoginIp" not in expected:
            actual.pop("lastLoginIp", None)
        if "lastLoginTime" not in expected:
            actual.pop("lastLoginTime", None)
    elif obj_type == ModelType.EVENT.value:
        del expected["metadata"]
        del expected["partition"]
    elif obj_type == ModelType.SENSOR.value:
        del expected["bridgeCandidates"]
        del expected["mountType"]

    # sometimes uptime comes back as a str...
    if "uptime" in expected and expected["uptime"] is not None:
        expected["uptime"] = int(expected["uptime"])

    # force hardware revision to str to make sure types line up
    if "hardwareRevision" in expected and expected["hardwareRevision"] is not None:
        expected["hardwareRevision"] = str(expected["hardwareRevision"])
        actual["hardwareRevision"] = str(actual["hardwareRevision"])

    assert expected == actual
