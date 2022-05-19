# type: ignore
# pylint: disable=protected-access

from datetime import timedelta

import pytest

from pyunifiprotect.data import Camera, Light
from pyunifiprotect.data.devices import Doorlock
from pyunifiprotect.data.types import LockStatusType
from pyunifiprotect.exceptions import BadRequest
from pyunifiprotect.utils import to_ms
from tests.conftest import TEST_CAMERA_EXISTS, TEST_DOORLOCK_EXISTS


@pytest.mark.skipif(not TEST_DOORLOCK_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_doorlock_set_paired_camera_none(doorlock_obj: Doorlock):
    doorlock_obj.api.api_request.reset_mock()

    doorlock_obj.camera_id = "bad_id"
    doorlock_obj._initial_data = doorlock_obj.dict()

    await doorlock_obj.set_paired_camera(None)

    doorlock_obj.api.api_request.assert_called_with(
        f"doorlocks/{doorlock_obj.id}",
        method="patch",
        json={"camera": None},
    )


@pytest.mark.skipif(not TEST_DOORLOCK_EXISTS or not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_doorlock_set_paired_camera(doorlock_obj: Light, camera_obj: Camera):
    doorlock_obj.api.api_request.reset_mock()

    doorlock_obj.camera_id = None
    doorlock_obj._initial_data = doorlock_obj.dict()

    await doorlock_obj.set_paired_camera(camera_obj)

    doorlock_obj.api.api_request.assert_called_with(
        f"doorlocks/{doorlock_obj.id}",
        method="patch",
        json={"camera": camera_obj.id},
    )


@pytest.mark.skipif(not TEST_DOORLOCK_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_doorlock_set_status_light(doorlock_obj: Doorlock, status: bool):
    doorlock_obj.api.api_request.reset_mock()

    doorlock_obj.led_settings.is_enabled = not status
    doorlock_obj._initial_data = doorlock_obj.dict()

    await doorlock_obj.set_status_light(status)

    doorlock_obj.api.api_request.assert_called_with(
        f"doorlocks/{doorlock_obj.id}",
        method="patch",
        json={"ledSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_DOORLOCK_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    "duration",
    [
        timedelta(seconds=0),
        timedelta(seconds=15),
        timedelta(seconds=3600),
        timedelta(seconds=3601),
    ],
)
@pytest.mark.asyncio
async def test_doorlock_set_auto_close_time(
    doorlock_obj: Doorlock,
    duration: timedelta,
):
    doorlock_obj.api.api_request.reset_mock()

    doorlock_obj.auto_close_time = timedelta(seconds=30)
    doorlock_obj._initial_data = doorlock_obj.dict()

    duration_invalid = duration is not None and int(duration.total_seconds()) == 3601
    if duration_invalid:
        with pytest.raises(BadRequest):
            await doorlock_obj.set_auto_close_time(duration)

            assert not doorlock_obj.api.api_request.called
    else:
        await doorlock_obj.set_auto_close_time(duration)

        expected = {"autoCloseTimeMs": to_ms(duration)}

        doorlock_obj.api.api_request.assert_called_with(
            f"doorlocks/{doorlock_obj.id}",
            method="patch",
            json=expected,
        )


@pytest.mark.skipif(not TEST_DOORLOCK_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_doorlock_close(doorlock_obj: Doorlock):
    doorlock_obj.api.api_request.reset_mock()

    doorlock_obj.lock_status = LockStatusType.OPEN
    doorlock_obj._initial_data = doorlock_obj.dict()

    await doorlock_obj.close_lock()

    doorlock_obj.api.api_request.assert_called_with(
        f"doorlocks/{doorlock_obj.id}/close",
        method="post",
    )


@pytest.mark.skipif(not TEST_DOORLOCK_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_doorlock_close_invalid(doorlock_obj: Doorlock):
    doorlock_obj.api.api_request.reset_mock()

    doorlock_obj.lock_status = LockStatusType.CLOSED
    doorlock_obj._initial_data = doorlock_obj.dict()

    with pytest.raises(BadRequest):
        await doorlock_obj.close_lock()

    assert not doorlock_obj.api.api_request.called


@pytest.mark.skipif(not TEST_DOORLOCK_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_doorlock_open(doorlock_obj: Doorlock):
    doorlock_obj.api.api_request.reset_mock()

    doorlock_obj.lock_status = LockStatusType.CLOSED
    doorlock_obj._initial_data = doorlock_obj.dict()

    await doorlock_obj.open_lock()

    doorlock_obj.api.api_request.assert_called_with(
        f"doorlocks/{doorlock_obj.id}/open",
        method="post",
    )


@pytest.mark.skipif(not TEST_DOORLOCK_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_doorlock_open_invalid(doorlock_obj: Doorlock):
    doorlock_obj.api.api_request.reset_mock()

    doorlock_obj.lock_status = LockStatusType.OPEN
    doorlock_obj._initial_data = doorlock_obj.dict()

    with pytest.raises(BadRequest):
        await doorlock_obj.open_lock()

    assert not doorlock_obj.api.api_request.called
