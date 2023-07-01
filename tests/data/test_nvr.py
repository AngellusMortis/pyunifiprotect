# type: ignore
# pylint: disable=protected-access

from __future__ import annotations

from datetime import timedelta
from ipaddress import IPv4Address, IPv6Address

import pytest

from pyunifiprotect.data import (
    NVR,
    AnalyticsOption,
    DoorbellMessage,
    DoorbellMessageType,
)
from pyunifiprotect.exceptions import BadRequest
from pyunifiprotect.utils import to_ms

try:
    from pydantic.v1 import ValidationError
except ImportError:
    from pydantic import ValidationError  # type: ignore


@pytest.mark.parametrize("status", [True, False])
@pytest.mark.asyncio
async def test_nvr_set_insights(nvr_obj: NVR, status: bool):
    nvr_obj.api.api_request.reset_mock()

    nvr_obj.is_insights_enabled = not status

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


@pytest.mark.parametrize(
    "ip,expected",
    [
        ("192.168.1.1", IPv4Address("192.168.1.1")),
        ("fe80::1ff:fe23:4567:890a", IPv6Address("fe80::1ff:fe23:4567:890a")),
    ],
)
@pytest.mark.asyncio
async def test_nvr_wan_ip(nvr_obj: NVR, ip: str, expected: IPv4Address | IPv6Address):
    nvr_dict = nvr_obj.unifi_dict()
    nvr_dict["wanIp"] = ip

    nvr = NVR.from_unifi_dict(**nvr_dict)
    assert nvr.wan_ip == expected
    assert nvr.unifi_dict()["wanIp"] == ip
