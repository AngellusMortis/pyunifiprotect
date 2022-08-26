# type: ignore
# pylint: disable=protected-access

from datetime import timedelta

from pydantic.error_wrappers import ValidationError
import pytest

from pyunifiprotect.data import (
    NVR,
    AnalyticsOption,
    DoorbellMessage,
    DoorbellMessageType,
)
from pyunifiprotect.exceptions import BadRequest
from pyunifiprotect.utils import to_ms


@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_nvr_set_insights(nvr_obj: NVR, status: bool):
    nvr_obj.api.api_request.reset_mock()

    nvr_obj.is_insights_enabled = not status
    nvr_obj._initial_data = nvr_obj.dict()

    await nvr_obj.set_insights(status)

    nvr_obj.api.api_request.assert_called_with(
        "nvr",
        method="patch",
        json={"isInsightsEnabled": status},
    )


@pytest.mark.asyncio
async def test_nvr_set_anonymous_analytics(nvr_obj: NVR):
    nvr_obj.api.api_request.reset_mock()

    nvr_obj.analytics_data = AnalyticsOption.ANONYMOUS
    nvr_obj._initial_data = nvr_obj.dict()

    await nvr_obj.set_anonymous_analytics(False)

    nvr_obj.api.api_request.assert_called_with(
        "nvr",
        method="patch",
        json={"analyticsData": "none"},
    )


@pytest.mark.asyncio
async def test_nvr_set_default_reset_timeout(nvr_obj: NVR):
    nvr_obj.api.api_request.reset_mock()

    duration = timedelta(seconds=10)
    await nvr_obj.set_default_reset_timeout(duration)

    nvr_obj.api.api_request.assert_called_with(
        "nvr",
        method="patch",
        json={"doorbellSettings": {"defaultMessageResetTimeoutMs": to_ms(duration)}},
    )


@pytest.mark.parametrize("message", ["Test", "fqthpqBgVMKXp9jXX2VeuGeXYfx2mMjB"])
@pytest.mark.asyncio
async def test_nvr_set_default_doorbell_message(nvr_obj: NVR, message: str):
    nvr_obj.api.api_request.reset_mock()

    if len(message) > 30:
        with pytest.raises(ValidationError):
            await nvr_obj.set_default_doorbell_message(message)

        assert not nvr_obj.api.api_request.called
    else:
        await nvr_obj.set_default_doorbell_message(message)

        nvr_obj.api.api_request.assert_called_with(
            "nvr",
            method="patch",
            json={"doorbellSettings": {"defaultMessageText": message}},
        )


@pytest.mark.parametrize("message", ["Welcome", "Test", "fqthpqBgVMKXp9jXX2VeuGeXYfx2mMjB"])
@pytest.mark.asyncio
async def test_nvr_add_custom_doorbell_message(nvr_obj: NVR, message: str):
    nvr_obj.api.api_request.reset_mock()

    nvr_obj.doorbell_settings.custom_messages = ["Welcome"]
    nvr_obj._initial_data = nvr_obj.dict()

    if message != "Test":
        with pytest.raises(BadRequest):
            await nvr_obj.add_custom_doorbell_message(message)

        assert not nvr_obj.api.api_request.called
    else:
        await nvr_obj.add_custom_doorbell_message(message)

        nvr_obj.api.api_request.assert_called_with(
            "nvr", method="patch", json={"doorbellSettings": {"customMessages": ["Welcome", "Test"]}}
        )

        assert nvr_obj.doorbell_settings.all_messages == [
            DoorbellMessage(
                type=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR,
                text=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value.replace("_", " "),
            ),
            DoorbellMessage(
                type=DoorbellMessageType.DO_NOT_DISTURB,
                text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
            ),
            DoorbellMessage(
                type=DoorbellMessageType.CUSTOM_MESSAGE,
                text="Welcome",
            ),
            DoorbellMessage(
                type=DoorbellMessageType.CUSTOM_MESSAGE,
                text="Test",
            ),
        ]


@pytest.mark.parametrize("message", ["Welcome", "Test"])
@pytest.mark.asyncio
async def test_nvr_remove_custom_doorbell_message(nvr_obj: NVR, message: str):
    nvr_obj.api.api_request.reset_mock()

    nvr_obj.doorbell_settings.custom_messages = ["Welcome"]
    nvr_obj._initial_data = nvr_obj.dict()

    if message == "Test":
        with pytest.raises(BadRequest):
            await nvr_obj.remove_custom_doorbell_message(message)

        assert not nvr_obj.api.api_request.called
    else:
        await nvr_obj.remove_custom_doorbell_message(message)

        nvr_obj.api.api_request.assert_called_with(
            "nvr", method="patch", json={"doorbellSettings": {"customMessages": []}}
        )

        assert nvr_obj.doorbell_settings.all_messages == [
            DoorbellMessage(
                type=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR,
                text=DoorbellMessageType.LEAVE_PACKAGE_AT_DOOR.value.replace("_", " "),
            ),
            DoorbellMessage(
                type=DoorbellMessageType.DO_NOT_DISTURB,
                text=DoorbellMessageType.DO_NOT_DISTURB.value.replace("_", " "),
            ),
        ]
