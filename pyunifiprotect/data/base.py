"""Unifi Protect Data."""
from __future__ import annotations

from datetime import datetime, timedelta
from ipaddress import IPv4Address
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Dict,
    Optional,
    Type,
    TypeVar,
    Union,
)

from pydantic import BaseModel
from pydantic.fields import PrivateAttr

from pyunifiprotect.data.types import ModelType, StateType
from pyunifiprotect.exceptions import BadRequest, DataDecodeError
from pyunifiprotect.utils import process_datetime, serialize_unifi_obj, to_snake_case

if TYPE_CHECKING:
    from pyunifiprotect.data.nvr import Event
    from pyunifiprotect.unifi_protect_server import ProtectApiClient


T = TypeVar("T", bound="ProtectBaseObject ")


class ProtectBaseObject(BaseModel):
    _api: Optional[ProtectApiClient] = PrivateAttr(None)
    _initial_data: Dict[str, Any] = PrivateAttr()

    UNIFI_REMAP: ClassVar[Dict[str, str]] = {}
    PROTECT_OBJ_FIELDS: ClassVar[Dict[str, Callable]] = {}

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, api=None, **data: Any) -> None:
        data["api"] = api
        data = self.clean_unifi_dict(data)
        super().__init__(**data)

        self._api = api

    @classmethod
    def _get_api(cls, data: Dict[str, Any]) -> Optional[ProtectApiClient]:
        api = data.get("api")

        if api is None and hasattr(cls, "_api"):
            api = cls._api

        return api

    @classmethod
    def clean_unifi_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        for from_key, to_key in cls.UNIFI_REMAP.items():
            if from_key in data:
                data[to_key] = data.pop(from_key)

        for key, klass in cls.PROTECT_OBJ_FIELDS.items():
            if key in data and isinstance(data[key], dict):
                obj_dict = data[key]
                obj_dict["api"] = cls._get_api(data)
                data[key] = klass.clean_unifi_dict(data=obj_dict)  # type: ignore

        for key in list(data.keys()):
            data[to_snake_case(key)] = data.pop(key)

        return data

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if data is None:
            data = self.dict()

        for key in self.PROTECT_OBJ_FIELDS:
            key = to_snake_case(key)
            key = self.UNIFI_REMAP.get(key, key)

            if key in data:
                unifi_obj: Optional[Any] = getattr(self, key)
                if unifi_obj is not None and isinstance(unifi_obj, ProtectBaseObject):
                    data[key] = unifi_obj.unifi_dict(data=data[key])

        data: Dict[str, Any] = serialize_unifi_obj(data)

        for to_key, from_key in self.UNIFI_REMAP.items():
            if from_key in data:
                data[to_key] = data.pop(from_key)

        if "api" in data:
            del data["api"]

        return data

    def update_from_dict(self: T, data: Dict[str, Any]) -> T:
        for key in self.PROTECT_OBJ_FIELDS:
            key = to_snake_case(key)
            key = self.UNIFI_REMAP.get(key, key)

            if key in data:
                unifi_obj: Optional[Any] = getattr(self, key)
                if unifi_obj is not None and isinstance(unifi_obj, ProtectBaseObject):
                    setattr(self, key, unifi_obj.update_from_dict(data.pop(key)))

        if "api" in data:
            del data["api"]

        return self.copy(update=data)

    def update_from_unifi_dict(self: T, data: Dict[str, Any]) -> T:
        data = self.clean_unifi_dict(data)
        return self.update_from_dict(data)

    @property
    def api(self) -> ProtectApiClient:
        if self._api is None:
            raise BadRequest("API Client not initialized")

        return self._api


class ProtectModel(ProtectBaseObject):
    model: Optional[ModelType]

    UNIFI_REMAP: ClassVar[Dict[str, str]] = {"modelKey": "model"}

    @staticmethod
    def klass_from_dict(data: Dict[str, Any]) -> Type[ProtectModel]:
        from pyunifiprotect.data.devices import (  # pylint: disable=import-outside-toplevel
            Bridge,
            Camera,
            Light,
            Viewer,
        )
        from pyunifiprotect.data.nvr import (  # pylint: disable=import-outside-toplevel
            NVR,
            CloudAccount,
            Event,
            Group,
            Liveview,
            User,
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
        elif model == ModelType.BRIDGE:
            klass = Bridge

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

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data)

        if "modelKey" in data and data["modelKey"] is None:
            del data["modelKey"]

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
    hardware_revision: Optional[Union[str, int]]
    firmware_version: str
    is_updating: bool
    is_ssh_enabled: bool

    @classmethod
    def clean_unifi_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "lastSeen" in data:
            data["lastSeen"] = process_datetime(data, "lastSeen")
        if "upSince" in data and data["upSince"] is not None:
            data["upSince"] = process_datetime(data, "upSince")
        if "uptime" in data and data["uptime"] is not None and not isinstance(data["uptime"], timedelta):
            data["uptime"] = timedelta(milliseconds=int(data["uptime"]))

        return super().clean_unifi_dict(data)


class WiredConnectionState(ProtectBaseObject):
    phy_rate: Optional[int]


class WifiConnectionState(WiredConnectionState):
    channel: Optional[int]
    frequency: Optional[int]
    signal_quality: Optional[int]
    signal_strength: Optional[int]
    ssid: Optional[str]


class ProtectAdoptableDeviceModel(ProtectDeviceModel):
    state: StateType
    connection_host: IPv4Address
    connected_since: Optional[datetime]
    latest_firmware_version: Optional[str]
    firmware_build: Optional[str]
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

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data)

        if "wiredConnectionState" in data and data["wiredConnectionState"] is None:
            del data["wiredConnectionState"]
        if "wifiConnectionState" in data and data["wifiConnectionState"] is None:
            del data["wifiConnectionState"]

        return data


class ProtectMotionDeviceModel(ProtectAdoptableDeviceModel):
    last_motion: Optional[datetime]
    is_dark: bool

    # not directly from Unifi
    last_motion_event_id: Optional[str] = None

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data)

        if "lastMotionEventId" in data:
            del data["lastMotionEventId"]

        return data

    @property
    def last_motion_event(self) -> Optional[Event]:
        if self.last_motion_event_id is None:
            return None

        return self.api.bootstrap.events.get(self.last_motion_event_id)
