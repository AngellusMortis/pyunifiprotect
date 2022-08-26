# pylint: disable=protected-access

import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from shlex import split
from subprocess import run
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest
import pytest_asyncio

from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data import Camera, ModelType
from pyunifiprotect.data.nvr import Event
from pyunifiprotect.data.types import EventType
from pyunifiprotect.utils import set_debug, set_no_debug
from tests.sample_data.constants import CONSTANTS

UFP_SAMPLE_DIR = os.environ.get("UFP_SAMPLE_DIR")
if UFP_SAMPLE_DIR:
    SAMPLE_DATA_DIRECTORY = Path(UFP_SAMPLE_DIR)
else:
    SAMPLE_DATA_DIRECTORY = Path(__file__).parent / "sample_data"

CHECK_CMD = "ffprobe -v error -select_streams v:0 -show_entries stream=codec_type -of csv=p=0 {filename}"
LENGTH_CMD = "ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {filename}"

TEST_CAMERA_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_camera.json").exists()
TEST_SNAPSHOT_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_camera_snapshot.png").exists()
TEST_VIDEO_EXISTS = (
    SAMPLE_DATA_DIRECTORY / "sample_camera_video.mp4"
).exists() or "camera_video_length" not in CONSTANTS
TEST_THUMBNAIL_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_camera_thumbnail.png").exists()
TEST_HEATMAP_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_camera_heatmap.png").exists()
TEST_SMART_TRACK_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_event_smart_track.json").exists()
TEST_LIGHT_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_light.json").exists()
TEST_SENSOR_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_sensor.json").exists()
TEST_VIEWPORT_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_viewport.json").exists()
TEST_BRIDGE_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_bridge.json").exists()
TEST_LIVEVIEW_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_liveview.json").exists()
TEST_DOORLOCK_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_doorlock.json").exists()
TEST_CHIME_EXISTS = (SAMPLE_DATA_DIRECTORY / "sample_chime.json").exists()


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
    if url.startswith("thumbnails/") or url.endswith("thumbnail"):
        return read_binary_file("sample_camera_thumbnail")
    elif url.startswith("cameras/"):
        return read_binary_file("sample_camera_snapshot")
    elif url.startswith("heatmaps/") or url.endswith("heatmap"):
        return read_binary_file("sample_camera_heatmap")
    elif url == "video/export":
        return read_binary_file("sample_camera_video", "mp4")
    return b""


async def mock_api_request(url: str, *args, **kwargs):
    if url == "bootstrap":
        return read_json_file("sample_bootstrap")
    elif url == "nvr":
        return read_json_file("sample_bootstrap")["nvr"]
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
    elif url == "doorlocks":
        return [read_json_file("sample_doorlock")]
    elif url == "chimes":
        return [read_json_file("sample_chime")]
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
    elif url.startswith("doorlocks"):
        return read_json_file("sample_doorlock")
    elif url.startswith("chimes"):
        return read_json_file("sample_chime")
    elif "smartDetectTrack" in url:
        return read_json_file("sample_event_smart_track")

    return {}


class SimpleMockWebsocket:
    is_closed: bool = False
    now: float = 0
    events: Dict[str, Any]
    count = 0

    def __init__(self):
        self.events = []

    @property
    def closed(self):
        return self.is_closed

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
        super().__init__()

        self.events = read_json_file("sample_ws_messages")


MockDatetime = Mock()
MockDatetime.now.return_value = get_now()
MockDatetime.utcnow.return_value = get_now()


@pytest.fixture(autouse=True)
def ensure_debug():
    set_debug()


async def setup_client(client: ProtectApiClient, websocket: SimpleMockWebsocket, timeout: int = 0):
    mock_cs = Mock()
    mock_session = AsyncMock()
    mock_session.ws_connect = AsyncMock(return_value=websocket)
    mock_cs.return_value = mock_session

    ws = await client.get_websocket()
    ws.timeout_interval = timeout
    ws._get_session = mock_cs  # type: ignore
    client.api_request = AsyncMock(side_effect=mock_api_request)  # type: ignore
    client.api_request_raw = AsyncMock(side_effect=mock_api_request_raw)  # type: ignore
    client.ensure_authenticated = AsyncMock()  # type: ignore
    await client.update()

    return client


async def cleanup_client(client: ProtectApiClient):
    await client.async_disconnect_ws()
    await client.close_session()


@pytest_asyncio.fixture(name="protect_client")
async def protect_client_fixture():
    client = ProtectApiClient("127.0.0.1", 0, "username", "password")
    yield await setup_client(client, SimpleMockWebsocket())
    await cleanup_client(client)


@pytest_asyncio.fixture
async def protect_client_no_debug():
    set_no_debug()

    client = ProtectApiClient("127.0.0.1", 0, "username", "password")
    yield await setup_client(client, SimpleMockWebsocket())
    await cleanup_client(client)


@pytest_asyncio.fixture
async def protect_client_ws():
    set_no_debug()

    client = ProtectApiClient("127.0.0.1", 0, "username", "password")
    yield await setup_client(client, MockWebsocket(), timeout=30)
    await cleanup_client(client)


@pytest_asyncio.fixture
async def smart_dectect_obj(protect_client: ProtectApiClient, raw_events):
    event_dict = None
    for event in raw_events:
        if event["type"] == EventType.SMART_DETECT.value:
            event_dict = event
            break

    if event_dict is None:
        yield None
    else:
        yield Event.from_unifi_dict(api=protect_client, **event_dict)


@pytest_asyncio.fixture
async def nvr_obj(protect_client: ProtectApiClient):
    yield protect_client.bootstrap.nvr


@pytest_asyncio.fixture
async def camera_obj(protect_client: ProtectApiClient):
    if not TEST_CAMERA_EXISTS:
        return None

    return list(protect_client.bootstrap.cameras.values())[0]


@pytest_asyncio.fixture
async def light_obj(protect_client: ProtectApiClient):
    if not TEST_LIGHT_EXISTS:
        return None

    return list(protect_client.bootstrap.lights.values())[0]


@pytest_asyncio.fixture
async def viewer_obj(protect_client: ProtectApiClient):
    if not TEST_VIEWPORT_EXISTS:
        return None

    return list(protect_client.bootstrap.viewers.values())[0]


@pytest_asyncio.fixture
async def sensor_obj(protect_client: ProtectApiClient):
    if not TEST_SENSOR_EXISTS:
        return None

    return list(protect_client.bootstrap.sensors.values())[0]


@pytest_asyncio.fixture(name="doorlock_obj")
async def doorlock_obj_fixture(protect_client: ProtectApiClient):
    if not TEST_DOORLOCK_EXISTS:
        return None

    return list(protect_client.bootstrap.doorlocks.values())[0]


@pytest_asyncio.fixture(name="chime_obj")
async def chime_obj_fixture(protect_client: ProtectApiClient):
    if not TEST_CHIME_EXISTS:
        return None

    return list(protect_client.bootstrap.chimes.values())[0]


@pytest_asyncio.fixture
async def liveview_obj(protect_client: ProtectApiClient):
    if not TEST_LIVEVIEW_EXISTS:
        return None

    return list(protect_client.bootstrap.liveviews.values())[0]


@pytest_asyncio.fixture
async def user_obj(protect_client: ProtectApiClient):
    return protect_client.bootstrap.auth_user


@pytest.fixture
def liveview():
    if not TEST_LIVEVIEW_EXISTS:
        return None

    return read_json_file("sample_liveview")


@pytest.fixture
def viewport():
    if not TEST_VIEWPORT_EXISTS:
        return None

    return read_json_file("sample_viewport")


@pytest.fixture
def light():
    if not TEST_LIGHT_EXISTS:
        return None

    return read_json_file("sample_light")


@pytest.fixture
def camera():
    if not TEST_CAMERA_EXISTS:
        return None

    return read_json_file("sample_camera")


@pytest.fixture
def sensor():
    if not TEST_SENSOR_EXISTS:
        return None

    return read_json_file("sample_sensor")


@pytest.fixture
def doorlock():
    if not TEST_DOORLOCK_EXISTS:
        return None

    return read_json_file("sample_doorlock")


@pytest.fixture
def chime():
    if not TEST_CHIME_EXISTS:
        return None

    return read_json_file("sample_chime")


@pytest.fixture
def bridge():
    if not TEST_BRIDGE_EXISTS:
        return None

    return read_json_file("sample_bridge")


@pytest.fixture
def liveviews():
    if not TEST_LIVEVIEW_EXISTS:
        return []

    return [read_json_file("sample_liveview")]


@pytest.fixture
def viewports():
    if not TEST_VIEWPORT_EXISTS:
        return []

    return [read_json_file("sample_viewport")]


@pytest.fixture
def lights():
    if not TEST_LIGHT_EXISTS:
        return []

    return [read_json_file("sample_light")]


@pytest.fixture
def cameras():
    if not TEST_CAMERA_EXISTS:
        return []

    return [read_json_file("sample_camera")]


@pytest.fixture
def sensors():
    if not TEST_SENSOR_EXISTS:
        return []

    return [read_json_file("sample_sensor")]


@pytest.fixture
def doorlocks():
    if not TEST_DOORLOCK_EXISTS:
        return []

    return [read_json_file("sample_doorlock")]


@pytest.fixture
def chimes():
    if not TEST_CHIME_EXISTS:
        return []

    return [read_json_file("sample_chime")]


@pytest.fixture
def bridges():
    if not TEST_BRIDGE_EXISTS:
        return []

    return [read_json_file("sample_bridge")]


@pytest.fixture
def ws_messages():
    return read_json_file("sample_ws_messages")


@pytest.fixture(name="raw_events")
def raw_events_fixture():
    return read_json_file("sample_raw_events")


@pytest.fixture
def bootstrap():
    return read_json_file("sample_bootstrap")


@pytest.fixture
def nvr():
    return read_json_file("sample_bootstrap")["nvr"]


@pytest.fixture
def smart_track():
    if not TEST_SMART_TRACK_EXISTS:
        return None

    return read_json_file("sample_event_smart_track")


@pytest.fixture
def now():
    return get_now().replace(tzinfo=timezone.utc)


@pytest.fixture
def tmp_binary_file():
    tmp_file = NamedTemporaryFile(mode="wb", delete=False)

    yield tmp_file

    try:
        tmp_file.close()
    except Exception:  # pylint: disable=broad-except
        pass

    os.remove(tmp_file.name)


# new values added for newer versions of UFP (for backwards compat tests)
NEW_FIELDS = {
    # 1.20.1
    "voltage",
    # 1.21.0-beta1
    "timestamp",
    "isWirelessUplinkEnabled",
    "marketName",
    # 1.21.0-beta3
    "isPoorNetwork",
    # 2.0-beta2
    "scopes",
    "streamSharingAvailable",
    "isDbAvailable",
    "isRecordingDisabled",
    "isRecordingMotionOnly",
    # 2.1.1-beta3
    "anonymousDeviceId",  # added to viewport
    "isStacked",
    "isPrimary",
    "lastDriveSlowEvent",
    "isUCoreSetup",
    # 2.2.1-beta2
    "isInsightsEnabled",
}


def compare_objs(obj_type, expected, actual):
    expected = deepcopy(expected)
    actual = deepcopy(actual)

    # TODO: fields not supported yet
    if obj_type == ModelType.CAMERA.value:
        # fields does not always exist (G4 Instant)
        if "apMac" in expected:
            del expected["apMac"]
        if "elementInfo" in expected:
            del expected["elementInfo"]
        del expected["apRssi"]
        del expected["lastPrivacyZonePositionId"]
        del expected["recordingSchedules"]
        del expected["smartDetectLines"]
        if "streamSharing" in expected:
            del expected["streamSharing"]
        del expected["featureFlags"]["focus"]
        del expected["featureFlags"]["pan"]
        del expected["featureFlags"]["tilt"]
        del expected["featureFlags"]["zoom"]

        # do not compare detect zones because float math sucks
        assert len(expected["motionZones"]) == len(actual["motionZones"])
        assert len(expected["privacyZones"]) == len(actual["privacyZones"])
        assert len(expected["smartDetectZones"]) == len(actual["smartDetectZones"])

        expected["motionZones"] = actual["motionZones"] = []
        expected["privacyZones"] = actual["privacyZones"] = []
        expected["smartDetectZones"] = actual["smartDetectZones"] = []
        expected["recordingSettings"]["enableMotionDetection"] = expected["recordingSettings"].get(
            "enableMotionDetection"
        )
        expected["featureFlags"]["audio"] = expected["featureFlags"].get("audio", [])
        expected["featureFlags"]["audioCodecs"] = expected["featureFlags"].get("audioCodecs", [])
        expected["featureFlags"]["hasInfrared"] = expected["featureFlags"].get("hasInfrared")

        if expected["eventStats"]["motion"].get("recentHours") in [[None], None, []]:
            expected["eventStats"]["motion"].pop("recentHours", None)
            actual["eventStats"]["motion"].pop("recentHours", None)
        if expected["eventStats"]["smart"].get("recentHours") == [[None], None, []]:
            expected["eventStats"]["smart"].pop("recentHours", None)
            actual["eventStats"]["smart"].pop("recentHours", None)
        if "hotplug" in actual["featureFlags"] and "hotplug" not in expected["featureFlags"]:
            del actual["featureFlags"]["hotplug"]
        if "lensType" in actual["featureFlags"] and "lensType" not in expected["featureFlags"]:
            del actual["featureFlags"]["lensType"]
        if "audioTypes" in actual["smartDetectSettings"] and "audioTypes" not in expected["smartDetectSettings"]:
            del actual["smartDetectSettings"]["audioTypes"]
    elif obj_type == ModelType.USER.value:
        if "settings" in expected:
            expected.pop("settings", None)
        del expected["alertRules"]
        del expected["notificationsV2"]
        # lastLoginIp/lastLoginTime is not always present
        if "lastLoginIp" not in expected:
            actual.pop("lastLoginIp", None)
        if "lastLoginTime" not in expected:
            actual.pop("lastLoginTime", None)
    elif obj_type == ModelType.EVENT.value:
        del expected["partition"]

        expected_keys = (expected.get("metadata") or {}).keys()
        actual_keys = (actual.get("metadata") or {}).keys()
        # delete all extra metadata keys, many of which are not modeled
        for key in set(expected_keys).difference(actual_keys):
            del expected["metadata"][key]
    elif obj_type in (ModelType.SENSOR.value, ModelType.DOORLOCK.value):
        del expected["bridgeCandidates"]
        actual.pop("host", None)
        expected.pop("host", None)
    elif obj_type == ModelType.CHIME.value:
        del expected["apMac"]
        del expected["apRssi"]
        del expected["elementInfo"]
    elif obj_type == ModelType.NVR.value:
        # TODO:
        del expected["errorCode"]
        del expected["wifiSettings"]
        del expected["smartDetectAgreement"]
        expected["isDbAvailable"] = expected.get("isDbAvailable")
        expected["marketName"] = expected.get("marketName")
        expected["streamSharingAvailable"] = expected.get("streamSharingAvailable")
        expected["ports"]["piongw"] = expected["ports"].get("piongw")
        expected["ports"]["stacking"] = expected["ports"].get("stacking")
        expected["ports"]["emsJsonCLI"] = expected["ports"].get("emsJsonCLI")

        # float math...
        if expected["systemInfo"].get("ustorage") is not None:
            for index, disk in enumerate(expected["systemInfo"]["ustorage"]["disks"]):
                actual_disk = actual["systemInfo"]["ustorage"]["disks"][index]
                estimate = disk.get("estimate")
                actual_estimate = actual_disk.get("estimate")
                if estimate is not None and actual_estimate is not None:
                    if math.isclose(estimate, actual_estimate, rel_tol=0.01):
                        actual["systemInfo"]["ustorage"]["disks"][index]["estimate"] = estimate

            for index, device in enumerate(expected["systemInfo"]["ustorage"]["space"]):
                actual_device = actual["systemInfo"]["ustorage"]["space"][index]
                estimate = device.get("estimate")
                actual_estimate = actual_device.get("estimate")
                if estimate is not None and actual_estimate is not None:
                    if math.isclose(estimate, actual_estimate, rel_tol=0.01):
                        actual["systemInfo"]["ustorage"]["space"][index]["estimate"] = estimate

    if "bluetoothConnectionState" in expected:
        expected["bluetoothConnectionState"]["experienceScore"] = expected["bluetoothConnectionState"].get(
            "experienceScore"
        )

    if "wifiConnectionState" in expected:
        expected["wifiConnectionState"]["bssid"] = expected["wifiConnectionState"].get("bssid")
        expected["wifiConnectionState"]["txRate"] = expected["wifiConnectionState"].get("txRate")

    # sometimes uptime comes back as a str...
    if "uptime" in expected and expected["uptime"] is not None:
        expected["uptime"] = int(expected["uptime"])

    # force hardware revision to str to make sure types line up
    if "hardwareRevision" in expected and expected["hardwareRevision"] is not None:
        expected["hardwareRevision"] = str(expected["hardwareRevision"])
        actual["hardwareRevision"] = str(actual["hardwareRevision"])

    for key in NEW_FIELDS.intersection(actual.keys()):
        if key not in expected:
            del actual[key]

    assert expected == actual


@pytest.fixture
def disable_camera_validation():
    Camera.__config__.validate_assignment = False

    yield

    Camera.__config__.validate_assignment = True


class MockTalkback:
    is_error: bool = False
    stdout: List[str] = []
    stderr: List[str] = []

    def __init__(self) -> None:
        self.start = AsyncMock()
        self.stop = AsyncMock()
        self.run_until_complete = AsyncMock()
