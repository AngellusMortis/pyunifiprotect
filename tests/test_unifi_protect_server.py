"""Tests for pyunifiprotect.unifi_protect_server."""
# pylint: disable=protected-access

import asyncio
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from PIL import Image
import pytest

from pyunifiprotect import UpvServer
from pyunifiprotect.unifi_data import EventType, ModelType
from pyunifiprotect.utils import to_js_time
from tests.conftest import MockDatetime, MockWebsocket
from tests.sample_data.constants import CONSTANTS


@pytest.mark.asyncio
async def test_upvserver_creation():
    """Test we can create the object."""

    upv = UpvServer(None, "127.0.0.1", 0, "username", "password")
    assert upv


@pytest.mark.asyncio
async def test_websocket(old_protect_client: UpvServer, ws_messages: Dict[str, Dict[str, Any]]):
    # wait for ws connection
    for _ in range(60):
        if old_protect_client.is_ws_connected:
            break
        await asyncio.sleep(0.5)

    ws_connect: Optional[MockWebsocket] = old_protect_client._ws_connection  # type: ignore
    assert ws_connect is not None

    while old_protect_client.is_ws_connected:
        await asyncio.sleep(0.1)

    assert ws_connect.count == len(ws_messages)
    assert ws_connect.now == float(list(ws_messages.keys())[-1])


@pytest.mark.asyncio
async def test_server_info(old_protect_client: UpvServer):
    data = await old_protect_client.server_information()

    old_protect_client.api_request.assert_called_with(  # type: ignore
        url="bootstrap",
        method="get",
        require_auth=True,
        raise_exception=True,
    )
    assert data == {
        "server_id": CONSTANTS["server_id"],
        "server_model": CONSTANTS["server_model"],
        "server_name": CONSTANTS["server_name"],
        "server_version": CONSTANTS["server_version"],
        "server_ip": CONSTANTS["server_ip"],
    }


@pytest.mark.asyncio
@patch("pyunifiprotect.unifi_protect_server.datetime", MockDatetime)
async def test_get_raw_events(old_protect_client: UpvServer, now: datetime):
    events = await old_protect_client.get_raw_events()

    old_protect_client.api_request.assert_called_with(  # type: ignore
        url="events",
        method="get",
        require_auth=True,
        raise_exception=True,
        params={
            "end": str(to_js_time(now + timedelta(seconds=10))),
            "start": str(to_js_time(now - timedelta(seconds=86400))),
        },
    )
    assert len(events) == CONSTANTS["event_count"]
    for event in events:
        event_type: str = event["type"]
        model_type: str = event["modelKey"]

        assert event_type in EventType.values()
        assert model_type in ModelType.values()


@pytest.mark.asyncio
async def test_raw_devices(old_protect_client: UpvServer):
    all_model_types = [e.value for e in ModelType]

    data = await old_protect_client.get_raw_device_info()

    old_protect_client.api_request.assert_called_with(  # type: ignore
        url="bootstrap",
        method="get",
        require_auth=True,
        raise_exception=True,
    )
    assert data.pop("authUserId") == CONSTANTS["user_id"]
    assert data.pop("lastUpdateId") == CONSTANTS["last_update_id"]
    data.pop("accessKey")
    data.pop("legacyUFVs")
    data.pop("nvr")
    for key in data.keys():
        model_type = key[:-1]
        assert model_type in all_model_types
        assert len(data[key]) == CONSTANTS["counts"][model_type]
        for item in data[key]:
            assert item["modelKey"] == model_type


@pytest.mark.skipif(CONSTANTS.get("camera_thumbnail") is None, reason="No Camera thumbnail in test data")
@pytest.mark.asyncio
async def test_get_thumbnail(old_protect_client: UpvServer, camera):
    data = await old_protect_client.get_thumbnail(camera_id=camera["id"])

    old_protect_client.api_request_raw.assert_called_with(  # type: ignore
        f"thumbnails/{old_protect_client._processed_data[camera['id']]['event_thumbnail']}",
        params={
            "h": "360.0",
            "w": "640",
        },
    )

    assert data is not None
    img = Image.open(BytesIO(data))
    assert img.width in (360, 640)  # Unifi may give a square image even though we did not request one
    assert img.height == 360


@pytest.mark.asyncio
@pytest.mark.skipif(not CONSTANTS.get("camera_online"), reason="No online camera in test data")
@patch("pyunifiprotect.unifi_protect_server.datetime", MockDatetime)
async def test_get_snapshot(old_protect_client: UpvServer, now, camera):
    data = await old_protect_client.get_snapshot_image(camera_id=camera["id"])
    if data is None:
        return

    height = old_protect_client.devices[camera["id"]].get("image_height")
    width = old_protect_client.devices[camera["id"]].get("image_width")

    old_protect_client.api_request_raw.assert_called_with(  # type: ignore
        f"cameras/{camera['id']}/snapshot",
        params={
            "h": height,
            "ts": str(to_js_time(now)),
            "force": "true",
            "w": width,
        },
        raise_exception=False,
    )

    img = Image.open(BytesIO(data))
    assert img.width == width
    assert img.height == height


@pytest.mark.asyncio
async def test_get_live_views(old_protect_client: UpvServer, liveviews: List[Dict[str, Any]]):
    data = await old_protect_client.get_live_views()

    old_protect_client.api_request.assert_called_with(  # type: ignore
        url="liveviews",
        method="get",
        require_auth=True,
        raise_exception=True,
    )

    for view in data:
        mock_view = None

        for item in liveviews:
            if item.get("id") == view.get("id"):
                mock_view = item
                break

        assert mock_view is not None
        assert len(view.keys()) == 2
        assert view["id"] == mock_view["id"]
        assert view["name"] == mock_view["name"]
