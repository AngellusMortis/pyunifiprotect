# type: ignore
# pylint: disable=protected-access

from datetime import timedelta
from typing import Optional

from pydantic.error_wrappers import ValidationError
import pytest

from pyunifiprotect.data import Camera, Light
from pyunifiprotect.data.types import LightModeEnableType, LightModeType
from pyunifiprotect.exceptions import BadRequest
from pyunifiprotect.utils import to_ms
from tests.conftest import TEST_CAMERA_EXISTS, TEST_LIGHT_EXISTS


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_light_set_paired_camera_none(light_obj: Light):
    light_obj.api.api_request.reset_mock()

    light_obj.camera_id = "bad_id"
    light_obj._initial_data = light_obj.dict()

    await light_obj.set_paired_camera(None)

    light_obj.api.api_request.assert_called_with(
        f"lights/{light_obj.id}",
        method="patch",
        json={"camera": None},
    )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS or not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_light_set_paired_camera(light_obj: Light, camera_obj: Camera):
    light_obj.api.api_request.reset_mock()

    light_obj.camera_id = None
    light_obj._initial_data = light_obj.dict()

    await light_obj.set_paired_camera(camera_obj)

    light_obj.api.api_request.assert_called_with(
        f"lights/{light_obj.id}",
        method="patch",
        json={"camera": camera_obj.id},
    )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_light_set_status_light(light_obj: Light, status: bool):
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.is_indicator_enabled = not status
    light_obj._initial_data = light_obj.dict()

    await light_obj.set_status_light(status)

    light_obj.api.api_request.assert_called_with(
        f"lights/{light_obj.id}",
        method="patch",
        json={"lightDeviceSettings": {"isIndicatorEnabled": status}},
    )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("level", [-1, 1, 3, 6, 7])
@pytest.mark.asyncio
async def test_light_set_led_level(light_obj: Light, level: int):
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.led_level = 2
    light_obj._initial_data = light_obj.dict()

    if level in (-1, 7):
        with pytest.raises(ValidationError):
            await light_obj.set_led_level(level)

            assert not light_obj.api.api_request.called
    else:
        await light_obj.set_led_level(level)

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json={"lightDeviceSettings": {"ledLevel": level}},
        )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.parametrize("level", [None, -1, 1, 3, 6, 7])
@pytest.mark.asyncio
async def test_light_set_light(light_obj: Light, status: bool, level: Optional[int]):
    light_obj.api.api_request.reset_mock()

    light_obj.light_on_settings.is_led_force_on = not status
    if level is not None:
        light_obj.light_device_settings.led_level = 2
    light_obj._initial_data = light_obj.dict()

    if level in (-1, 7):
        with pytest.raises(ValidationError):
            await light_obj.set_light(status, level)

            assert not light_obj.api.api_request.called
    else:
        await light_obj.set_light(status, level)

        if level is None:
            expected = {"lightOnSettings": {"isLedForceOn": status}}
        else:
            expected = {"lightOnSettings": {"isLedForceOn": status}, "lightDeviceSettings": {"ledLevel": level}}

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json=expected,
        )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("sensitivity", [1, 100, -10])
@pytest.mark.asyncio
async def test_light_set_sensitivity(
    light_obj: Light,
    sensitivity: int,
):
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.pir_sensitivity = 50
    light_obj._initial_data = light_obj.dict()

    if sensitivity == -10:
        with pytest.raises(ValidationError):
            await light_obj.set_sensitivity(sensitivity)

            assert not light_obj.api.api_request.called
    else:
        await light_obj.set_sensitivity(sensitivity)

        expected = {"lightDeviceSettings": {"pirSensitivity": sensitivity}}

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json=expected,
        )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize(
    "duration",
    [
        timedelta(seconds=1),
        timedelta(seconds=15),
        timedelta(seconds=900),
        timedelta(seconds=1000),
    ],
)
@pytest.mark.asyncio
async def test_light_set_duration(
    light_obj: Light,
    duration: timedelta,
):
    light_obj.api.api_request.reset_mock()

    light_obj.light_device_settings.pir_duration = timedelta(seconds=30)
    light_obj._initial_data = light_obj.dict()

    duration_invalid = duration is not None and int(duration.total_seconds()) in (1, 1000)
    if duration_invalid:
        with pytest.raises(BadRequest):
            await light_obj.set_duration(duration)

            assert not light_obj.api.api_request.called
    else:
        await light_obj.set_duration(duration)

        expected = {"lightDeviceSettings": {"pirDuration": to_ms(duration)}}

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json=expected,
        )


@pytest.mark.skipif(not TEST_LIGHT_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("mode", [LightModeType.MANUAL, LightModeType.WHEN_DARK])
@pytest.mark.parametrize("enable_at", [None, LightModeEnableType.ALWAYS])
@pytest.mark.parametrize(
    "duration",
    [
        None,
        timedelta(seconds=1),
        timedelta(seconds=15),
        timedelta(seconds=900),
        timedelta(seconds=1000),
    ],
)
@pytest.mark.parametrize("sensitivity", [None, 1, 100, -10])
@pytest.mark.asyncio
async def test_light_set_light_settings(
    light_obj: Light,
    mode: LightModeType,
    enable_at: Optional[LightModeEnableType],
    duration: Optional[timedelta],
    sensitivity: Optional[int],
):
    light_obj.api.api_request.reset_mock()

    light_obj.light_mode_settings.mode = LightModeType.MOTION
    light_obj.light_mode_settings.enable_at = LightModeEnableType.DARK
    light_obj.light_device_settings.pir_duration = timedelta(seconds=30)
    light_obj.light_device_settings.pir_sensitivity = 50
    light_obj._initial_data = light_obj.dict()

    duration_invalid = duration is not None and int(duration.total_seconds()) in (1, 1000)
    if duration_invalid:
        with pytest.raises(BadRequest):
            await light_obj.set_light_settings(mode, enable_at=enable_at, duration=duration, sensitivity=sensitivity)

            assert not light_obj.api.api_request.called
    elif sensitivity == -10:
        with pytest.raises(ValidationError):
            await light_obj.set_light_settings(mode, enable_at=enable_at, duration=duration, sensitivity=sensitivity)

            assert not light_obj.api.api_request.called
    else:
        await light_obj.set_light_settings(mode, enable_at=enable_at, duration=duration, sensitivity=sensitivity)

        expected = {"lightModeSettings": {"mode": mode.value}}
        if enable_at is not None:
            expected["lightModeSettings"].update({"enableAt": enable_at.value})
        if duration is not None:
            expected["lightDeviceSettings"] = expected.get("lightDeviceSettings", {})
            expected["lightDeviceSettings"].update({"pirDuration": to_ms(duration)})
        if sensitivity is not None:
            expected["lightDeviceSettings"] = expected.get("lightDeviceSettings", {})
            expected["lightDeviceSettings"].update({"pirSensitivity": sensitivity})

        light_obj.api.api_request.assert_called_with(
            f"lights/{light_obj.id}",
            method="patch",
            json=expected,
        )
