# type: ignore
# pylint: disable=protected-access

from pydantic.error_wrappers import ValidationError
import pytest

from pyunifiprotect.data import Camera, Light
from pyunifiprotect.data.devices import Sensor
from pyunifiprotect.data.types import MountType
from pyunifiprotect.exceptions import BadRequest
from tests.conftest import TEST_CAMERA_EXISTS, TEST_SENSOR_EXISTS


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_sensor_set_status_light(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.led_settings.is_enabled = not status
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_status_light(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"ledSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("mount_type", [MountType.DOOR, MountType.NONE])
@pytest.mark.asyncio
async def test_sensor_set_mount_type(sensor_obj: Sensor, mount_type: MountType):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.mount_type = MountType.LEAK
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_mount_type(mount_type)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"mountType": mount_type.value},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_sensor_set_motion_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.motion_settings.is_enabled = not status
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_motion_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"motionSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_sensor_set_temperature_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.temperature_settings.is_enabled = not status
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_temperature_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"temperatureSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_sensor_set_humidity_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.humidity_settings.is_enabled = not status
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_humidity_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"humiditySettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_sensor_set_light_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.light_settings.is_enabled = not status
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_light_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"lightSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_sensor_set_alarm_status(sensor_obj: Sensor, status: bool):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.alarm_settings.is_enabled = not status
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_alarm_status(status)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"alarmSettings": {"isEnabled": status}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("sensitivity", [1, 100, -10])
@pytest.mark.asyncio
async def test_sensor_set_motion_sensitivity(
    sensor_obj: Sensor,
    sensitivity: int,
):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.motion_settings.sensitivity = 50
    sensor_obj._initial_data = sensor_obj.dict()

    if sensitivity == -10:
        with pytest.raises(ValidationError):
            await sensor_obj.set_motion_sensitivity(sensitivity)

            assert not sensor_obj.api.api_request.called
    else:
        await sensor_obj.set_motion_sensitivity(sensitivity)

        sensor_obj.api.api_request.assert_called_with(
            f"sensors/{sensor_obj.id}",
            method="patch",
            json={"motionSettings": {"sensitivity": sensitivity}},
        )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("low", [-1.0, 0.0, 25.0])
@pytest.mark.parametrize("high", [20.0, 45.0, 50.0])
@pytest.mark.asyncio
async def test_sensor_set_temperature_safe_range(sensor_obj: Sensor, low: float, high: float):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.temperature_settings.low_threshold = None
    sensor_obj.temperature_settings.high_threshold = None
    sensor_obj._initial_data = sensor_obj.dict()

    if low == -1.0 or high == 50.0 or low > high:
        with pytest.raises(BadRequest):
            await sensor_obj.set_temperature_safe_range(low, high)

            assert not sensor_obj.api.api_request.called
    else:
        await sensor_obj.set_temperature_safe_range(low, high)

        sensor_obj.api.api_request.assert_called_with(
            f"sensors/{sensor_obj.id}",
            method="patch",
            json={"temperatureSettings": {"lowThreshold": low, "highThreshold": high}},
        )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("low", [0.0, 1.0, 50.0])
@pytest.mark.parametrize("high", [45.0, 99.0, 100.0])
@pytest.mark.asyncio
async def test_sensor_set_humidity_safe_range(sensor_obj: Sensor, low: float, high: float):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.humidity_settings.low_threshold = None
    sensor_obj.humidity_settings.high_threshold = None
    sensor_obj._initial_data = sensor_obj.dict()

    if low == 0.0 or high == 100.0 or low > high:
        with pytest.raises(BadRequest):
            await sensor_obj.set_humidity_safe_range(low, high)

            assert not sensor_obj.api.api_request.called
    else:
        await sensor_obj.set_humidity_safe_range(low, high)

        sensor_obj.api.api_request.assert_called_with(
            f"sensors/{sensor_obj.id}",
            method="patch",
            json={"humiditySettings": {"lowThreshold": low, "highThreshold": high}},
        )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("low", [0.0, 1.0, 500.0])
@pytest.mark.parametrize("high", [400.0, 1000.0, 1001.0])
@pytest.mark.asyncio
async def test_sensor_set_light_safe_range(sensor_obj: Sensor, low: float, high: float):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.light_settings.low_threshold = None
    sensor_obj.light_settings.high_threshold = None
    sensor_obj._initial_data = sensor_obj.dict()

    if low == 0.0 or high == 1001.0 or low > high:
        with pytest.raises(BadRequest):
            await sensor_obj.set_light_safe_range(low, high)

            assert not sensor_obj.api.api_request.called
    else:
        await sensor_obj.set_light_safe_range(low, high)

        sensor_obj.api.api_request.assert_called_with(
            f"sensors/{sensor_obj.id}",
            method="patch",
            json={"lightSettings": {"lowThreshold": low, "highThreshold": high}},
        )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_sensor_remove_temperature_safe_range(sensor_obj: Sensor):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.temperature_settings.low_threshold = 10
    sensor_obj.temperature_settings.high_threshold = 20
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.remove_temperature_safe_range()

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"temperatureSettings": {"lowThreshold": None, "highThreshold": None}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_sensor_remove_humidity_safe_range(sensor_obj: Sensor):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.humidity_settings.low_threshold = 10
    sensor_obj.humidity_settings.high_threshold = 20
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.remove_humidity_safe_range()

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"humiditySettings": {"lowThreshold": None, "highThreshold": None}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_sensor_remove_light_safe_range(sensor_obj: Sensor):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.light_settings.low_threshold = 10
    sensor_obj.light_settings.high_threshold = 20
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.remove_light_safe_range()

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"lightSettings": {"lowThreshold": None, "highThreshold": None}},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_sensor_set_paired_camera_none(sensor_obj: Sensor):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.camera_id = "bad_id"
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_paired_camera(None)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"camera": None},
    )


@pytest.mark.skipif(not TEST_SENSOR_EXISTS or not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_sensor_set_paired_camera(sensor_obj: Light, camera_obj: Camera):
    sensor_obj.api.api_request.reset_mock()

    sensor_obj.camera_id = None
    sensor_obj._initial_data = sensor_obj.dict()

    await sensor_obj.set_paired_camera(camera_obj)

    sensor_obj.api.api_request.assert_called_with(
        f"sensors/{sensor_obj.id}",
        method="patch",
        json={"camera": camera_obj.id},
    )
