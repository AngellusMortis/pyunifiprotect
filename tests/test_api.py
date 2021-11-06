"""Tests for pyunifiprotect.unifi_protect_server."""
# pylint: disable=pointless-statement
# pylint: disable=protected-access

from datetime import datetime, timedelta
from io import BytesIO
from ipaddress import IPv4Address
import logging
import time
from unittest.mock import AsyncMock, patch

from PIL import Image
import pytest

from pyunifiprotect.api import NEVER_RAN, WEBSOCKET_CHECK_INTERVAL, ProtectApiClient
from pyunifiprotect.data import (
    Camera,
    Event,
    EventType,
    ModelType,
    create_from_unifi_dict,
)
from pyunifiprotect.data.base import ProtectAdoptableDeviceModel
from pyunifiprotect.data.bootstrap import Bootstrap
from pyunifiprotect.exceptions import BadRequest, NvrError
from pyunifiprotect.utils import to_js_time
from tests.conftest import (
    SAMPLE_DATA_DIRECTORY,
    MockDatetime,
    compare_objs,
    validate_video_file,
)
from tests.sample_data.constants import CONSTANTS


async def check_motion_event(event: Event):
    data = await event.get_thumbnail()
    assert data is not None
    img = Image.open(BytesIO(data))
    assert img.format in ("PNG", "JPEG")

    data = await event.get_heatmap()
    assert data is not None
    img = Image.open(BytesIO(data))
    assert img.format in ("PNG", "JPEG")


async def check_camera(camera: Camera):
    if camera.last_motion_event is not None:
        await check_motion_event(camera.last_motion_event)

    if camera.last_smart_detect_event is not None:
        await check_motion_event(camera.last_smart_detect_event)

    data = await camera.get_snapshot()
    assert data is not None
    img = Image.open(BytesIO(data))
    assert img.format in ("PNG", "JPEG")

    camera.last_ring_event

    assert camera.timelapse_url == f"https://127.0.0.1:0/protect/timelapse/{camera.id}"
    check_device(camera)

    for channel in camera.channels:
        if channel.is_rtsp_enabled:
            assert channel.rtsp_url == f"rtsp://{camera.api.connection_host}:7447/{channel.rtsp_alias}"
            assert channel.rtsps_url == f"rtsps://{camera.api.connection_host}:7441/{channel.rtsp_alias}?enableSrtp"


def check_device(device: ProtectAdoptableDeviceModel):
    assert device.protect_url == f"https://127.0.0.1:0/protect/devices/{device.id}"


async def check_bootstrap(bootstrap: Bootstrap):
    assert bootstrap.auth_user
    assert bootstrap.nvr.protect_url == f"https://127.0.0.1:0/protect/devices/{bootstrap.nvr.id}"

    for light in bootstrap.lights.values():
        if light.camera is not None:
            await check_camera(light.camera)
        light.last_motion_event
        check_device(light)

    for camera in bootstrap.cameras.values():
        await check_camera(camera)

    for viewer in bootstrap.viewers.values():
        assert viewer.liveview
        check_device(viewer)

    for sensor in bootstrap.sensors.values():
        check_device(sensor)

    for liveview in bootstrap.liveviews.values():
        liveview.owner
        assert liveview.protect_url == f"https://127.0.0.1:0/protect/liveview/{liveview.id}"

        for slot in liveview.slots:
            assert len(slot.camera_ids) == len(slot.cameras)

    for user in bootstrap.users.values():
        user.groups

        if user.cloud_account is not None:
            assert user.cloud_account.user == user

    for event in bootstrap.events.values():
        event.smart_detect_events

        if event.type.value in EventType.motion_events() and event.camera is not None:
            await check_motion_event(event)


def test_base_url(protect_client: ProtectApiClient):
    assert protect_client.base_url == "https://127.0.0.1:0"
    assert protect_client.base_ws_url == "wss://127.0.0.1:0"

    protect_client._port = 443

    assert protect_client.base_url == "https://127.0.0.1"
    assert protect_client.base_ws_url == "wss://127.0.0.1"


def test_api_client_creation():
    """Test we can create the object."""

    client = ProtectApiClient("127.0.0.1", 0, "username", "password", debug=True)
    assert client


def test_early_bootstrap():
    client = ProtectApiClient("127.0.0.1", 0, "username", "password", debug=True)

    with pytest.raises(BadRequest):
        client.bootstrap


def test_connection_host(protect_client: ProtectApiClient):
    # mismatch between client IP and IP that NVR returns
    assert protect_client.connection_host == IPv4Address(CONSTANTS["server_ip"])

    protect_client._host = CONSTANTS["server_ip"]
    protect_client._connection_host = None

    # same IP from client and NVR
    assert protect_client.connection_host == IPv4Address(CONSTANTS["server_ip"])


@pytest.mark.asyncio
async def test_force_update(protect_client: ProtectApiClient):
    protect_client._bootstrap = None

    await protect_client.update(force=True)

    assert protect_client.bootstrap


@pytest.mark.asyncio
async def test_bootstrap(protect_client: ProtectApiClient):
    """Verifies lookup of all object via ID"""

    await check_bootstrap(protect_client.bootstrap)


@pytest.mark.asyncio
async def test_bootstrap_construct(protect_client_no_debug: ProtectApiClient):
    """Verifies lookup of all object via ID"""

    await check_bootstrap(protect_client_no_debug.bootstrap)


@pytest.mark.asyncio
@patch("pyunifiprotect.api.datetime", MockDatetime)
async def test_get_events_raw_default(protect_client: ProtectApiClient, now: datetime):
    events = await protect_client.get_events_raw()

    end = now + timedelta(seconds=10)

    protect_client.api_request.assert_called_with(  # type: ignore
        url="events",
        method="get",
        require_auth=True,
        raise_exception=True,
        params={
            "start": to_js_time(end - timedelta(hours=24)),
            "end": to_js_time(end),
        },
    )
    assert len(events) == CONSTANTS["event_count"]
    for event in events:
        assert event["type"] in EventType.values()
        assert event["modelKey"] in ModelType.values()


@pytest.mark.asyncio
async def test_get_events_raw_limit(protect_client: ProtectApiClient):
    await protect_client.get_events_raw(limit=10)

    protect_client.api_request.assert_called_with(  # type: ignore
        url="events",
        method="get",
        require_auth=True,
        raise_exception=True,
        params={"limit": 10},
    )


@pytest.mark.asyncio
async def test_get_events_raw_cameras(protect_client: ProtectApiClient):
    await protect_client.get_events_raw(limit=10, camera_ids=["test1", "test2"])

    protect_client.api_request.assert_called_with(  # type: ignore
        url="events",
        method="get",
        require_auth=True,
        raise_exception=True,
        params={"limit": 10, "cameras": "test1,test2"},
    )


@pytest.mark.asyncio
async def test_get_events(protect_client: ProtectApiClient, raw_events):
    expected_events = []
    for event in raw_events:
        if event["score"] >= 50 and event["type"] in EventType.device_events():
            expected_events.append(event)

    protect_client._minimum_score = 50

    events = await protect_client.get_events()

    assert len(events) == len(expected_events)
    for index, event in enumerate(events):
        compare_objs(event.model.value, expected_events[index], event.unifi_dict())

        if event.type.value in EventType.motion_events():
            await check_motion_event(event)


@pytest.mark.asyncio
async def test_get_events_not_event(protect_client: ProtectApiClient, camera):
    protect_client.get_events_raw = AsyncMock(return_value=[camera])  # type: ignore

    assert await protect_client.get_events() == []


@pytest.mark.asyncio
async def test_get_events_not_event_with_type(protect_client: ProtectApiClient, camera):
    camera["type"] = EventType.MOTION.value

    protect_client.get_events_raw = AsyncMock(return_value=[camera])  # type: ignore

    assert await protect_client.get_events() == []


@pytest.mark.asyncio
async def test_check_ws_initial(protect_client: ProtectApiClient, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)

    protect_client._last_websocket_check = NEVER_RAN
    protect_client.disconnect_ws()
    protect_client.ws_connection = None

    active_ws = await protect_client.check_ws()

    assert active_ws is True
    assert ["Checking websocket"] == [rec.message for rec in caplog.records]


@pytest.mark.asyncio
async def test_check_ws_no_ws(protect_client: ProtectApiClient, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)

    protect_client._last_websocket_check = time.monotonic()
    protect_client.disconnect_ws()
    protect_client.ws_connection = None

    active_ws = await protect_client.check_ws()

    assert active_ws is False

    expected_logs = ["Unifi OS: Websocket connection not active, failing back to polling"]
    assert expected_logs == [rec.message for rec in caplog.records]
    assert caplog.records[0].levelname == "DEBUG"


@pytest.mark.asyncio
async def test_check_ws_reconnect(protect_client: ProtectApiClient, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)

    protect_client._last_websocket_check = time.monotonic() - WEBSOCKET_CHECK_INTERVAL - 1
    protect_client.disconnect_ws()
    protect_client.ws_connection = None

    active_ws = await protect_client.check_ws()

    assert active_ws is True
    expected_logs = ["Checking websocket", "Unifi OS: Websocket connection not active, failing back to polling"]
    assert expected_logs == [rec.message for rec in caplog.records]
    assert caplog.records[1].levelname == "WARNING"


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_camera.json").exists(), reason="No camera in testdata")
@pytest.mark.asyncio
async def test_get_device_mismatch(protect_client: ProtectApiClient, camera):
    protect_client.api_request_obj = AsyncMock(return_value=camera)  # type: ignore

    with pytest.raises(NvrError):
        await protect_client.get_bridge("test_id")


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_camera.json").exists(), reason="No camera in testdata")
@pytest.mark.asyncio
async def test_get_camera(protect_client: ProtectApiClient, camera):
    obj = create_from_unifi_dict(camera)

    assert obj == await protect_client.get_camera("test_id")


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_light.json").exists(), reason="No light in testdata")
@pytest.mark.asyncio
async def test_get_light(protect_client: ProtectApiClient, light):
    obj = create_from_unifi_dict(light)

    assert obj == await protect_client.get_light("test_id")


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_sensor.json").exists(), reason="No sensor in testdata")
@pytest.mark.asyncio
async def test_get_sensor(protect_client: ProtectApiClient, sensor):
    obj = create_from_unifi_dict(sensor)

    assert obj == await protect_client.get_sensor("test_id")


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_viewport.json").exists(), reason="No viewport in testdata")
@pytest.mark.asyncio
async def test_get_viewer(protect_client: ProtectApiClient, viewport):
    obj = create_from_unifi_dict(viewport)

    assert obj == await protect_client.get_viewer("test_id")


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_bridge.json").exists(), reason="No bridge in testdata")
@pytest.mark.asyncio
async def test_get_bridge(protect_client: ProtectApiClient, bridge):
    obj = create_from_unifi_dict(bridge)

    assert obj == await protect_client.get_bridge("test_id")


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_liveview.json").exists(), reason="No liveview in testdata")
@pytest.mark.asyncio
async def test_get_liveview(protect_client: ProtectApiClient, liveview):
    obj = create_from_unifi_dict(liveview)

    assert obj == await protect_client.get_liveview("test_id")


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_camera.json").exists(), reason="No camera in testdata")
@pytest.mark.asyncio
async def test_get_devices_mismatch(protect_client: ProtectApiClient, cameras):
    protect_client.api_request_list = AsyncMock(return_value=cameras)  # type: ignore

    with pytest.raises(NvrError):
        await protect_client.get_bridges()


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_camera.json").exists(), reason="No camera in testdata")
@pytest.mark.asyncio
async def test_get_cameras(protect_client: ProtectApiClient, cameras):
    objs = [create_from_unifi_dict(d) for d in cameras]

    assert objs == await protect_client.get_cameras()


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_light.json").exists(), reason="No light in testdata")
@pytest.mark.asyncio
async def test_get_lights(protect_client: ProtectApiClient, lights):
    objs = [create_from_unifi_dict(d) for d in lights]

    assert objs == await protect_client.get_lights()


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_sensor.json").exists(), reason="No sensor in testdata")
@pytest.mark.asyncio
async def test_get_sensors(protect_client: ProtectApiClient, sensors):
    objs = [create_from_unifi_dict(d) for d in sensors]

    assert objs == await protect_client.get_sensors()


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_viewport.json").exists(), reason="No viewport in testdata")
@pytest.mark.asyncio
async def test_get_viewers(protect_client: ProtectApiClient, viewports):
    objs = [create_from_unifi_dict(d) for d in viewports]

    assert objs == await protect_client.get_viewers()


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_bridge.json").exists(), reason="No bridge in testdata")
@pytest.mark.asyncio
async def test_get_bridges(protect_client: ProtectApiClient, bridges):
    objs = [create_from_unifi_dict(d) for d in bridges]

    assert objs == await protect_client.get_bridges()


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_liveview.json").exists(), reason="No liveview in testdata")
@pytest.mark.asyncio
async def test_get_liveviews(protect_client: ProtectApiClient, liveviews):
    objs = [create_from_unifi_dict(d) for d in liveviews]

    assert objs == await protect_client.get_liveviews()


@pytest.mark.skipif(
    not (SAMPLE_DATA_DIRECTORY / "sample_camera_snapshot.png").exists(), reason="No snapshot in testdata"
)
@patch("pyunifiprotect.api.datetime", MockDatetime)
@pytest.mark.asyncio
async def test_get_camera_snapshot(protect_client: ProtectApiClient, now):
    data = await protect_client.get_camera_snapshot("test_id")
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore
        "cameras/test_id/snapshot",
        params={
            "ts": to_js_time(now),
            "force": "true",
        },
        raise_exception=False,
    )

    img = Image.open(BytesIO(data))
    assert img.format in ("PNG", "JPEG")


@pytest.mark.skipif(
    not (SAMPLE_DATA_DIRECTORY / "sample_camera_snapshot.png").exists(), reason="No snapshot in testdata"
)
@patch("pyunifiprotect.api.datetime", MockDatetime)
@pytest.mark.asyncio
async def test_get_camera_snapshot_args(protect_client: ProtectApiClient, now):
    data = await protect_client.get_camera_snapshot("test_id", 1920, 1080)
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore
        "cameras/test_id/snapshot",
        params={
            "ts": to_js_time(now),
            "force": "true",
            "w": 1920,
            "h": 1080,
        },
        raise_exception=False,
    )

    img = Image.open(BytesIO(data))
    assert img.format in ("PNG", "JPEG")


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_camera_video.mp4").exists(), reason="No video in testdata")
@patch("pyunifiprotect.api.datetime", MockDatetime)
@pytest.mark.asyncio
async def test_get_camera_video(protect_client: ProtectApiClient, now, tmp_binary_file):
    camera = list(protect_client.bootstrap.cameras.values())[0]
    start = now - timedelta(seconds=CONSTANTS["camera_video_length"])

    data = await protect_client.get_camera_video(camera.id, start, now)
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore
        "video/export",
        params={
            "camera": camera.id,
            "channel": 0,
            "start": to_js_time(start),
            "end": to_js_time(now),
        },
        raise_exception=False,
    )

    tmp_binary_file.write(data)
    tmp_binary_file.close()

    validate_video_file(tmp_binary_file.name, CONSTANTS["camera_video_length"])


@pytest.mark.skipif(
    not (SAMPLE_DATA_DIRECTORY / "sample_camera_thumbnail.png").exists(), reason="No thumbnail in testdata"
)
@pytest.mark.asyncio
async def test_get_event_thumbnail(protect_client: ProtectApiClient):
    data = await protect_client.get_event_thumbnail("test_id")
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore
        "thumbnails/test_id",
        params={},
        raise_exception=False,
    )

    img = Image.open(BytesIO(data))
    assert img.format in ("PNG", "JPEG")


@pytest.mark.skipif(
    not (SAMPLE_DATA_DIRECTORY / "sample_camera_thumbnail.png").exists(), reason="No thumbnail in testdata"
)
@pytest.mark.asyncio
async def test_get_event_thumbnail_args(protect_client: ProtectApiClient):
    data = await protect_client.get_event_thumbnail("test_id", 1920, 1080)
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore
        "thumbnails/test_id",
        params={
            "w": 1920,
            "h": 1080,
        },
        raise_exception=False,
    )

    img = Image.open(BytesIO(data))
    assert img.format in ("PNG", "JPEG")


@pytest.mark.skipif(not (SAMPLE_DATA_DIRECTORY / "sample_camera_heatmap.png").exists(), reason="No heatmap in testdata")
@pytest.mark.asyncio
async def test_get_event_heatmap(protect_client: ProtectApiClient):
    data = await protect_client.get_event_heatmap("test_id")
    assert data is not None

    protect_client.api_request_raw.assert_called_with(  # type: ignore
        "heatmaps/test_id",
        raise_exception=False,
    )

    img = Image.open(BytesIO(data))
    assert img.format in ("PNG", "JPEG")
