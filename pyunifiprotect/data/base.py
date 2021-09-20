"""Unifi Protect Data."""
from __future__ import annotations

from datetime import datetime, timedelta
from ipaddress import IPv4Address
from typing import TYPE_CHECKING, Any, Dict, Optional, Type

from pydantic import BaseModel
from pydantic.fields import PrivateAttr

from ..exceptions import DataDecodeError
from ..utils import (
    process_datetime,
    to_camel_case_dict,
    to_js_time,
    to_ms,
    to_snake_case,
)
from .types import ModelType, StateType

if TYPE_CHECKING:
    from ..unifi_protect_server import ProtectApiClient

SUPPORTED_PROTECT_MODELS = ["cameras", "users", "groups", "liveviews", "viewers", "lights"]


class ProtectBaseObject(BaseModel):
    _api: Optional[ProtectApiClient] = PrivateAttr(None)

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, api=None, **data: Any) -> None:
        for key in list(data.keys()):
            data[to_snake_case(key)] = data.pop(key)

        super().__init__(**data)

        self._api = api

    def unifi_dict(self):
        data = to_camel_case_dict(self.dict())

        return data


class ProtectModel(ProtectBaseObject):
    model: Optional[ModelType]

    def __init__(self, **kwargs):
        model_key = kwargs.pop("modelKey", None)
        if model_key is not None:
            kwargs["model"] = ModelType(model_key)

        super().__init__(**kwargs)

    @staticmethod
    def klass_from_dict(data: Dict[str, Any]) -> Type[ProtectModel]:
        from .devices import Camera, Light, Viewer  # pylint: disable=import-outside-toplevel
        from .nvr import (  # pylint: disable=import-outside-toplevel
            NVR,
            CloudAccount,
            Event,
            Group,
            User,
            Liveview,
            UserLocation,
        )

        if "modelKey" not in data:
            raise DataDecodeError("No modelKey")

        model = ModelType(data["modelKey"])

        klass: Optional[Type[ProtectModel]] = None

        if model == ModelType.EVENT:
            klass = Event
        elif model == ModelType.GROUP:
            klass = Group
        elif model == ModelType.USER_LOCATION:
            klass = UserLocation
        elif model == ModelType.CLOUD_IDENTITY:
            klass = CloudAccount
        elif model == ModelType.USER:
            klass = User
        elif model == ModelType.NVR:
            klass = NVR
        elif model == ModelType.LIGHT:
            klass = Light
        elif model == ModelType.CAMERA:
            klass = Camera
        elif model == ModelType.LIVEVIEW:
            klass = Liveview
        elif model == ModelType.VIEWPORT:
            klass = Viewer

        if klass is None:
            raise DataDecodeError("Unknown modelKey")

        return klass

    @staticmethod
    def from_unifi_dict(
        data: Dict[str, Any], api: Optional[ProtectApiClient] = None, klass: Optional[Type[ProtectModel]] = None
    ) -> ProtectModel:
        if "modelKey" not in data:
            raise DataDecodeError("No modelKey")

        if klass is None:
            klass = ProtectModel.klass_from_dict(data)

        return klass(**data, api=api)

    def unifi_dict(self):
        data = super().unifi_dict()

        if data["model"] is None:
            del data["model"]
        else:
            data["modelKey"] = data.pop("model").value

        return data


class ProtectModelWithId(ProtectModel):
    id: str


class ProtectDeviceModel(ProtectModelWithId):
    name: str
    type: str
    mac: str
    host: IPv4Address
    up_since: Optional[datetime]
    uptime: Optional[timedelta]
    last_seen: datetime
    hardware_revision: Optional[str]
    firmware_version: str
    is_updating: bool
    is_ssh_enabled: bool

    def __init__(self, **kwargs):
        kwargs["lastSeen"] = process_datetime(kwargs, "lastSeen")

        if kwargs["upSince"] is not None:
            kwargs["upSince"] = process_datetime(kwargs, "upSince")

        if kwargs["uptime"] is not None:
            kwargs["uptime"] = timedelta(milliseconds=kwargs["uptime"])

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["lastSeen"] = to_js_time(data["lastSeen"])
        data["upSince"] = to_js_time(data["upSince"])
        data["host"] = str(data["host"])
        data["uptime"] = to_ms(data["uptime"])

        return data


class WiredConnectionState(ProtectBaseObject):
    phy_rate: Optional[int]


class WifiConnectionState(WiredConnectionState):
    channel: Optional[int]
    frequency: Optional[int]
    signal_quality: Optional[int]
    signal_strength: Optional[int]


class ProtectAdoptableDeviceModel(ProtectDeviceModel):
    state: StateType
    connection_host: IPv4Address
    connected_since: Optional[datetime]
    latest_firmware_version: str
    firmware_build: str
    is_adopting: bool
    is_adopted: bool
    is_adopted_by_other: bool
    is_provisioned: bool
    is_rebooting: bool
    can_adopt: bool
    is_attempting_to_connect: bool
    is_connected: bool

    wired_connection_state: Optional[WiredConnectionState] = None
    wifi_connection_state: Optional[WifiConnectionState] = None

    def unifi_dict(self):
        data = super().unifi_dict()
        data["connectionHost"] = str(data["connectionHost"])
        data["connectedSince"] = to_js_time(data["connectedSince"])

        if data["wiredConnectionState"] is None:
            del data["wiredConnectionState"]

        if data["wifiConnectionState"] is None:
            del data["wifiConnectionState"]

        return data


class ProtectMotionDeviceModel(ProtectAdoptableDeviceModel):
    last_motion: Optional[datetime]
    is_dark: bool

    def __init__(self, **kwargs):
        kwargs["lastMotion"] = process_datetime(kwargs, "lastMotion")

        super().__init__(**kwargs)

    def unifi_dict(self):
        data = super().unifi_dict()
        data["lastMotion"] = to_js_time(data["lastMotion"])

        return data
