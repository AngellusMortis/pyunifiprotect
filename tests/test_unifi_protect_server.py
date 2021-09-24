"""Tests for pyunifiprotect.unifi_protect_server."""
# pylint: disable=pointless-statement

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from pyunifiprotect import ProtectApiClient
from pyunifiprotect.data import EventType, ModelType
from pyunifiprotect.utils import to_js_time
from tests.conftest import MockDatetime, compare_objs
from tests.sample_data.constants import CONSTANTS


@pytest.mark.asyncio
async def test_api_client_creation():
    """Test we can create the object."""

    client = ProtectApiClient("127.0.0.1", 0, "username", "password")
    assert client


@pytest.mark.asyncio
async def test_bootstrap(protect_client: ProtectApiClient):
    """Verifies lookup of all object via ID"""

    assert protect_client.bootstrap.auth_user

    for light in protect_client.bootstrap.lights.values():
        light.camera
        light.last_motion_event

    for camera in protect_client.bootstrap.cameras.values():
        camera.last_motion_event
        camera.last_ring_event
        camera.last_smart_detect_event

    for viewer in protect_client.bootstrap.viewers.values():
        assert viewer.liveview

    for liveview in protect_client.bootstrap.liveviews.values():
        liveview.owner

        for slot in liveview.slots:
            assert len(slot.camera_ids) == len(slot.cameras)

    for user in protect_client.bootstrap.users.values():
        user.groups

        if user.cloud_account is not None:
            assert user.cloud_account.user == user

    for event in protect_client.bootstrap.events.values():
        event.smart_detect_events


@pytest.mark.asyncio
@patch("pyunifiprotect.unifi_protect_server.datetime", MockDatetime)
async def test_get_events_raw_default(protect_client: ProtectApiClient, now: datetime):
    events = await protect_client.get_events_raw()

    end = now + timedelta(seconds=10)

    protect_client.api_request.assert_called_with(  # type: ignore
        "events",
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
        "events",
        params={"limit": 10},
    )


@pytest.mark.asyncio
async def test_get_events_raw_cameras(protect_client: ProtectApiClient):
    await protect_client.get_events_raw(limit=10, camera_ids=["test1", "test2"])

    protect_client.api_request.assert_called_with(  # type: ignore
        "events",
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
