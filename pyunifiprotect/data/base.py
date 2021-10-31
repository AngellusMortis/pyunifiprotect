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
    Set,
    Type,
    TypeVar,
    Union,
)

from pydantic import BaseModel
from pydantic.fields import SHAPE_DICT, SHAPE_LIST, PrivateAttr

from pyunifiprotect.data.types import ModelType, StateType
from pyunifiprotect.exceptions import BadRequest, DataDecodeError
from pyunifiprotect.utils import process_datetime, serialize_unifi_obj, to_snake_case

if TYPE_CHECKING:
    from pyunifiprotect.data.devices import Bridge
    from pyunifiprotect.data.nvr import Event
    from pyunifiprotect.unifi_protect_server import ProtectApiClient


T = TypeVar("T", bound="ProtectBaseObject")


class ProtectBaseObject(BaseModel):
    _api: Optional[ProtectApiClient] = PrivateAttr(None)
    _initial_data: Dict[str, Any] = PrivateAttr()

    _protect_objs: ClassVar[Optional[Dict[str, Callable]]] = None
    _protect_lists: ClassVar[Optional[Dict[str, Callable]]] = None
    _protect_dicts: ClassVar[Optional[Dict[str, Callable]]] = None

    UNIFI_REMAP: ClassVar[Dict[str, str]] = {}

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, api: Optional[ProtectApiClient] = None, **data: Any) -> None:
        data["api"] = api
        data = self.clean_unifi_dict(data)
        del data["api"]
        super().__init__(**data)

        self._api = api

    @classmethod
    def _set_project_subtypes(cls) -> None:
        cls._protect_objs = {}
        cls._protect_lists = {}
        cls._protect_dicts = {}

        for name, field in cls.__fields__.items():
            try:
                if issubclass(field.type_, ProtectBaseObject):
                    if field.shape == SHAPE_LIST:
                        cls._protect_lists[name] = field.type_
                    if field.shape == SHAPE_DICT:
                        cls._protect_dicts[name] = field.type_
                    else:
                        cls._protect_objs[name] = field.type_
            except TypeError:
                pass

    @classmethod
    def _get_protect_objs(cls) -> Dict[str, Type[ProtectBaseObject]]:
        if cls._protect_objs is not None:
            return cls._protect_objs  # type: ignore

        cls._set_project_subtypes()
        return cls._protect_objs  # type: ignore

    @classmethod
    def _get_protect_lists(cls) -> Dict[str, Type[ProtectBaseObject]]:
        if cls._protect_lists is not None:
            return cls._protect_lists  # type: ignore

        cls._set_project_subtypes()
        return cls._protect_lists  # type: ignore

    @classmethod
    def _get_protect_dicts(cls) -> Dict[str, Type[ProtectBaseObject]]:
        if cls._protect_dicts is not None:
            return cls._protect_dicts  # type: ignore

        cls._set_project_subtypes()
        return cls._protect_dicts  # type: ignore

    @classmethod
    def _get_api(cls, data: Dict[str, Any]) -> Optional[ProtectApiClient]:
        api = data.get("api")

        if api is None and isinstance(cls, ProtectBaseObject) and hasattr(cls, "_api"):
            api = cls._api

        return api

    @classmethod
    def clean_unifi_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        for from_key, to_key in cls.UNIFI_REMAP.items():
            if from_key in data:
                data[to_key] = data.pop(from_key)

        for key in list(data.keys()):
            data[to_snake_case(key)] = data.pop(key)

        for key, klass in cls._get_protect_objs().items():
            if key in data and isinstance(data[key], dict):
                obj_dict = data[key]
                api = cls._get_api(data)
                if api is not None:
                    obj_dict["api"] = api
                data[key] = klass.clean_unifi_dict(data=obj_dict)

        for key, klass in cls._get_protect_lists().items():
            if key in data and isinstance(data[key], list):
                obj_list = data[key]
                api = cls._get_api(data)
                cleaned_items = []
                for obj in obj_list:
                    if api is not None:
                        obj["api"] = api
                    cleaned_items.append(klass.clean_unifi_dict(data=obj))
                data[key] = cleaned_items

        for key, klass in cls._get_protect_dicts().items():
            if key in data and isinstance(data[key], dict):
                obj_dict = data[key]
                api = cls._get_api(data)
                cleaned_dict = {}
                for obj_key, value in obj_dict.items():
                    if api is not None:
                        value["api"] = api
                    cleaned_dict[obj_key] = klass.clean_unifi_dict(data=value)
                data[key] = cleaned_dict

        return data

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        use_obj = False
        if data is None:
            excluded_fields = set(self._get_protect_objs().keys()) | set(self._get_protect_lists().keys())
            if exclude is not None:
                excluded_fields = excluded_fields | exclude
            data = self.dict(exclude=excluded_fields)
            use_obj = True

        for key in self._get_protect_objs().keys():
            unifi_obj: Optional[Any] = None
            if use_obj:
                unifi_obj = getattr(self, key)
            elif key in data:
                unifi_obj = data[key]

            if isinstance(unifi_obj, ProtectBaseObject):
                data[key] = unifi_obj.unifi_dict()
            elif use_obj or key in data:
                data[key] = unifi_obj

        for key in self._get_protect_lists().keys():
            unifi_list: Optional[Any] = None
            if use_obj:
                unifi_list = getattr(self, key)
            elif key in data:
                unifi_list = data[key]

            if isinstance(unifi_list, list):
                objs = []
                for obj in unifi_list:
                    if isinstance(obj, ProtectBaseObject):
                        objs.append(obj.unifi_dict())
                    else:
                        objs.append(obj)
                data[key] = objs
            elif key in data:
                data[key] = unifi_list

        for key in self._get_protect_dicts().keys():
            unifi_dict: Optional[Any] = None
            if use_obj:
                unifi_dict = getattr(self, key)
            elif key in data:
                unifi_dict = data[key]

            if isinstance(unifi_dict, dict):
                obj_dict = {}
                for obj_key, value in unifi_dict.items():
                    if isinstance(value, ProtectBaseObject):
                        obj_dict[obj_key] = value.unifi_dict()
                    else:
                        obj_dict[obj_key] = value
                data[key] = obj_dict
            elif key in data:
                data[key] = unifi_dict

        data: Dict[str, Any] = serialize_unifi_obj(data)
        for to_key, from_key in self.UNIFI_REMAP.items():
            if from_key in data:
                data[to_key] = data.pop(from_key)

        if "api" in data:
            del data["api"]

        return data

    def update_from_dict(self: T, data: Dict[str, Any]) -> T:
        for key in self._get_protect_objs().keys():
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
            Sensor,
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
        elif model == ModelType.SENSOR:
            klass = Sensor

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

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "modelKey" in data and data["modelKey"] is None:
            del data["modelKey"]

        return data


class ProtectModelWithId(ProtectModel):
    id: str


class ProtectDeviceModel(ProtectModelWithId):
    name: str
    type: str
    mac: str
    host: Optional[IPv4Address]
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


class WirelessConnectionState(ProtectBaseObject):
    signal_quality: Optional[int]
    signal_strength: Optional[int]


class WifiConnectionState(WirelessConnectionState):
    phy_rate: Optional[int]
    channel: Optional[int]
    frequency: Optional[int]
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
    bluetooth_connection_state: Optional[WirelessConnectionState] = None
    bridge_id: Optional[str]

    # TODO:
    # bridgeCandidates

    UNIFI_REMAP: ClassVar[Dict[str, str]] = {**ProtectDeviceModel.UNIFI_REMAP, **{"bridge": "bridgeId"}}

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "wiredConnectionState" in data and data["wiredConnectionState"] is None:
            del data["wiredConnectionState"]
        if "wifiConnectionState" in data and data["wifiConnectionState"] is None:
            del data["wifiConnectionState"]
        if "bluetoothConnectionState" in data and data["bluetoothConnectionState"] is None:
            del data["bluetoothConnectionState"]
        if "bridge" in data and data["bridge"] is None:
            del data["bridge"]

        return data

    @property
    def is_wired(self) -> bool:
        return self.wired_connection_state is not None

    @property
    def is_wifi(self) -> bool:
        return self.wifi_connection_state is not None

    @property
    def is_bluetooth(self) -> bool:
        return self.bluetooth_connection_state is not None

    @property
    def bridge(self) -> Optional[Bridge]:
        if self.bridge_id is None:
            return None

        return self.api.bootstrap.bridges[self.bridge_id]


class ProtectMotionDeviceModel(ProtectAdoptableDeviceModel):
    last_motion: Optional[datetime]
    is_dark: bool

    # not directly from Unifi
    last_motion_event_id: Optional[str] = None

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "lastMotionEventId" in data:
            del data["lastMotionEventId"]

        return data

    @property
    def last_motion_event(self) -> Optional[Event]:
        if self.last_motion_event_id is None:
            return None

        return self.api.bootstrap.events.get(self.last_motion_event_id)
