"""Unifi Protect Data."""
from __future__ import annotations

from datetime import datetime, timedelta
from ipaddress import IPv4Address
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Dict,
    List,
    Optional,
    Set,
    Type,
    TypeVar,
)

from pydantic import BaseModel
from pydantic.fields import SHAPE_DICT, SHAPE_LIST, PrivateAttr

from pyunifiprotect.data.types import ModelType, ProtectWSPayloadFormat, StateType
from pyunifiprotect.data.websocket import (
    WSJSONPacketFrame,
    WSPacket,
    WSPacketFrameHeader,
)
from pyunifiprotect.exceptions import BadRequest
from pyunifiprotect.utils import (
    convert_unifi_data,
    dict_diff,
    is_debug,
    process_datetime,
    serialize_unifi_obj,
    to_snake_case,
)

if TYPE_CHECKING:
    from pydantic.typing import DictStrAny, SetStr

    from pyunifiprotect.api import ProtectApiClient
    from pyunifiprotect.data.devices import Bridge
    from pyunifiprotect.data.nvr import Event


ProtectObject = TypeVar("ProtectObject", bound="ProtectBaseObject")


class ProtectBaseObject(BaseModel):
    """
    Base class for building Python objects from Unifi Protect JSON.

    * Provides `.unifi_dict_to_dict` to convert UFP JSON to a more Pythonic formatted dict (camel case to snake case)
    * Add attrs with matching Pyhonic name and they will automatically be populated from the UFP JSON if passed in to the constructer
    * Provides `.unifi_dict` to convert object back into UFP JSON
    """

    _api: Optional[ProtectApiClient] = PrivateAttr(None)
    _initial_data: Dict[str, Any] = PrivateAttr()

    _protect_objs: ClassVar[Optional[Dict[str, Type[ProtectBaseObject]]]] = None
    _protect_objs_set: ClassVar[Optional[SetStr]] = None
    _protect_lists: ClassVar[Optional[Dict[str, Type[ProtectBaseObject]]]] = None
    _protect_lists_set: ClassVar[Optional[SetStr]] = None
    _protect_dicts: ClassVar[Optional[Dict[str, Type[ProtectBaseObject]]]] = None
    _protect_dicts_set: ClassVar[Optional[SetStr]] = None
    _to_unifi_remaps: ClassVar[Optional[DictStrAny]] = None

    class Config:
        arbitrary_types_allowed = True
        validate_assignment = True

    def __init__(self, api: Optional[ProtectApiClient] = None, **data: Any) -> None:
        """
        Base class for creating Python objects from UFP JSON data.

        Use the static method `.from_unifi_dict()` to create objects from UFP JSON data from then the main class constructor.
        """
        super().__init__(**data)

        self._initial_data = self.dict(exclude=self._get_excluded_changed_fields())
        self._api = api

    @classmethod
    def from_unifi_dict(cls, api: Optional[ProtectApiClient] = None, **data: Any) -> ProtectObject:
        """
        Main constructor for `ProtectBaseObject`

        Args:

        * `api`: Optional reference to the ProtectAPIClient that created generated the UFP JSON
        * `data`: decoded UFP JSON

        `api` is is expected as a `@property`. If it is `None` and accessed, a `BadRequest` will be raised.

        API can be used for saving updates for the Protect object or fetching references to other objects
        (cameras, users, etc.)
        """

        data["api"] = api
        data = cls.unifi_dict_to_dict(data)

        if is_debug():
            data.pop("api", None)
            return cls(api=api, **data)  # type: ignore

        obj = cls.construct(**data)
        return obj  # type: ignore

    @classmethod
    def construct(cls, _fields_set: Optional[Set[str]] = None, **values: Any) -> ProtectObject:
        api = values.pop("api", None)
        values_set = set(values)

        unifi_objs = cls._get_protect_objs()
        for key in cls._get_protect_objs_set().intersection(values_set):
            if isinstance(values[key], dict):
                values[key] = unifi_objs[key].construct(**values[key])

        unifi_lists = cls._get_protect_lists()
        for key in cls._get_protect_lists_set().intersection(values_set):
            if isinstance(values[key], list):
                values[key] = [unifi_lists[key].construct(**v) if isinstance(v, dict) else v for v in values[key]]

        unifi_dicts = cls._get_protect_dicts()
        for key in cls._get_protect_dicts_set().intersection(values_set):
            if isinstance(values[key], dict):
                values[key] = {
                    k: unifi_dicts[key].construct(**v) if isinstance(v, dict) else v for k, v in values[key].items()
                }

        obj = super().construct(_fields_set=_fields_set, **values)
        obj._initial_data = obj.dict(exclude=cls._get_excluded_changed_fields())  # pylint: disable=protected-access
        obj._api = api  # pylint: disable=protected-access

        return obj  # type: ignore

    @classmethod
    def _get_excluded_changed_fields(cls) -> Set[str]:
        """
        Helper method for override in child classes for fields that excluded from calculating "changed" state for a
        model (`.initial_data` and `.get_changed()`)
        """
        return set()

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        """
        Helper method for overriding in child classes for remapping UFP JSON keys to Python ones that do not fit the
        simple camel case to snake case formula.

        Return format is
        {
            "ufpJsonName": "python_name"
        }
        """

        return {}

    @classmethod
    def _get_to_unifi_remaps(cls) -> Dict[str, str]:
        """
        Helper method for overriding in child classes for reversing remap UFP
        JSON keys to Python ones that do not fit the simple camel case to
        snake case formula.

        Return format is
        {
            "python_name": "ufpJsonName"
        }
        """

        if cls._to_unifi_remaps is None:
            cls._to_unifi_remaps = {to_key: from_key for from_key, to_key in cls._get_unifi_remaps().items()}

        return cls._to_unifi_remaps

    @classmethod
    def _set_protect_subtypes(cls) -> None:
        """Helper method to detect attrs of current class that are UFP Objects themselves"""

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
        """Helper method to get all child UFP objects"""
        if cls._protect_objs is not None:
            return cls._protect_objs

        cls._set_protect_subtypes()
        return cls._protect_objs  # type: ignore

    @classmethod
    def _get_protect_objs_set(cls) -> Set[str]:
        """Helper method to get all child UFP objects"""
        if cls._protect_objs_set is None:
            cls._protect_objs_set = set(cls._get_protect_objs().keys())

        return cls._protect_objs_set

    @classmethod
    def _get_protect_lists(cls) -> Dict[str, Type[ProtectBaseObject]]:
        """Helper method to get all child of UFP objects (lists)"""
        if cls._protect_lists is not None:
            return cls._protect_lists

        cls._set_protect_subtypes()
        return cls._protect_lists  # type: ignore

    @classmethod
    def _get_protect_lists_set(cls) -> Set[str]:
        """Helper method to get all child UFP objects"""
        if cls._protect_lists_set is None:
            cls._protect_lists_set = set(cls._get_protect_lists().keys())

        return cls._protect_lists_set

    @classmethod
    def _get_protect_dicts(cls) -> Dict[str, Type[ProtectBaseObject]]:
        """Helper method to get all child of UFP objects (dicts)"""
        if cls._protect_dicts is not None:
            return cls._protect_dicts

        cls._set_protect_subtypes()
        return cls._protect_dicts  # type: ignore

    @classmethod
    def _get_protect_dicts_set(cls) -> Set[str]:
        """Helper method to get all child UFP objects"""
        if cls._protect_dicts_set is None:
            cls._protect_dicts_set = set(cls._get_protect_dicts().keys())

        return cls._protect_dicts_set

    @classmethod
    def _get_api(cls, api: Optional[ProtectApiClient]) -> Optional[ProtectApiClient]:
        """Helper method to try to find and the current ProjtectAPIClient instance from given data"""
        if api is None and isinstance(cls, ProtectBaseObject) and hasattr(cls, "_api"):
            api = cls._api

        return api

    @classmethod
    def _clean_protect_obj(cls, data: Any, klass: Type[ProtectBaseObject], api: Optional[ProtectApiClient]) -> Any:
        if isinstance(data, dict):
            if api is not None:
                data["api"] = api
            return klass.unifi_dict_to_dict(data=data)
        return data

    @classmethod
    def _clean_protect_obj_list(
        cls, items: List[Any], klass: Type[ProtectBaseObject], api: Optional[ProtectApiClient]
    ) -> List[Any]:
        for index, item in enumerate(items):
            items[index] = cls._clean_protect_obj(item, klass, api)
        return items

    @classmethod
    def _clean_protect_obj_dict(
        cls, items: Dict[Any, Any], klass: Type[ProtectBaseObject], api: Optional[ProtectApiClient]
    ) -> Dict[Any, Any]:
        for key, value in items.items():
            items[key] = cls._clean_protect_obj(value, klass, api)
        return items

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Takes a decoded UFP JSON dict and converts it into a Python dict

        * Remaps items from `._get_unifi_remaps()`
        * Converts camelCase keys to snake_case keys
        * Injects ProtectAPIClient into any child UFP object Dicts
        * Runs `.unifi_dict_to_dict` for any child UFP objects

        Args:

        * `data`: decoded UFP JSON dict
        """

        # get the API client instance
        api = cls._get_api(data.get("api", None))

        # remap keys that will not be converted correctly by snake_case convert
        remaps = cls._get_unifi_remaps()
        for from_key in set(remaps).intersection(data):
            data[remaps[from_key]] = data.pop(from_key)

        # convert to snake_case and remove extra fields
        for key in list(data.keys()):
            new_key = to_snake_case(key)
            data[new_key] = data.pop(key)
            key = new_key

            if key == "api":
                continue

            if key not in cls.__fields__:
                del data[key]
                continue
            data[key] = convert_unifi_data(data[key], cls.__fields__[key])

        # clean child UFP objs
        data_set = set(data)

        unifi_objs = cls._get_protect_objs()
        for key in cls._get_protect_objs_set().intersection(data_set):
            data[key] = cls._clean_protect_obj(data[key], unifi_objs[key], api)

        unifi_lists = cls._get_protect_lists()
        for key in cls._get_protect_lists_set().intersection(data_set):
            if isinstance(data[key], list):
                data[key] = cls._clean_protect_obj_list(data[key], unifi_lists[key], api)

        unifi_dicts = cls._get_protect_dicts()
        for key in cls._get_protect_dicts_set().intersection(data_set):
            if isinstance(data[key], dict):
                data[key] = cls._clean_protect_obj_dict(data[key], unifi_dicts[key], api)

        return data

    def _unifi_dict_protect_obj(self, data: Dict[str, Any], key: str, use_obj: bool) -> Any:
        value: Optional[Any] = data.get(key)
        if use_obj:
            value = getattr(self, key)

        if isinstance(value, ProtectBaseObject):
            value = value.unifi_dict()

        return value

    def _unifi_dict_protect_obj_list(self, data: Dict[str, Any], key: str, use_obj: bool) -> Any:
        value: Optional[Any] = data.get(key)
        if use_obj:
            value = getattr(self, key)

        if not isinstance(value, list):
            return value

        items: List[Any] = []
        for item in value:
            if isinstance(item, ProtectBaseObject):
                item = item.unifi_dict()
            items.append(item)

        return items

    def _unifi_dict_protect_obj_dict(self, data: Dict[str, Any], key: str, use_obj: bool) -> Any:
        value: Optional[Any] = data.get(key)
        if use_obj:
            value = getattr(self, key)

        if not isinstance(value, dict):
            return value

        items: Dict[Any, Any] = {}
        for obj_key, obj in value.items():
            if isinstance(obj, ProtectBaseObject):
                obj = obj.unifi_dict()
            items[obj_key] = obj

        return items

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        """
        Can either convert current Python object into UFP JSON dict or take the output of a `.dict()` call and convert it.

        * Remaps items from `._get_unifi_remaps()` in reverse
        * Converts snake_case to camelCase
        * Automatically removes any ProtectApiClient instances that might still be in the data
        * Automaitcally calls `.unifi_dict()` for any UFP Python objects that are detected

        Args:

        `data`: Optional output of `.dict()` for the Python object. If `None`, will call `.dict` first
        `exclude`: Optional set of fields to exclude from convert. Useful for subclassing and having custom
            processing for dumping to UFP JSON data.
        """

        use_obj = False
        if data is None:
            excluded_fields = self._get_protect_objs_set() | self._get_protect_lists_set()
            if exclude is not None:
                excluded_fields = excluded_fields | exclude
            data = self.dict(exclude=excluded_fields)
            use_obj = True

        for key in self._get_protect_objs().keys():
            if use_obj or key in data:
                data[key] = self._unifi_dict_protect_obj(data, key, use_obj)

        for key in self._get_protect_lists().keys():
            if use_obj or key in data:
                data[key] = self._unifi_dict_protect_obj_list(data, key, use_obj)

        for key in self._get_protect_dicts().keys():
            if use_obj or key in data:
                data[key] = self._unifi_dict_protect_obj_dict(data, key, use_obj)

        data: Dict[str, Any] = serialize_unifi_obj(data)
        remaps = self._get_to_unifi_remaps()
        for to_key in set(data).intersection(remaps):
            data[remaps[to_key]] = data.pop(to_key)

        if "api" in data:
            del data["api"]

        return data

    def _inject_api(self, data: Dict[str, Any], api: Optional[ProtectApiClient]) -> Dict[str, Any]:
        data["api"] = api
        data_set = set(data)

        for key in self._get_protect_objs_set().intersection(data_set):
            unifi_obj: Optional[Any] = getattr(self, key)
            if unifi_obj is not None and isinstance(unifi_obj, dict):
                unifi_obj["api"] = api

        for key in self._get_protect_lists_set().intersection(data_set):
            new_items = []
            for item in data[key]:
                if isinstance(item, dict):
                    item["api"] = api
                new_items.append(item)
            data[key] = new_items

        for key in self._get_protect_dicts_set().intersection(data_set):
            for item_key, item in data[key].items():
                if isinstance(item, dict):
                    item["api"] = api
                data[key][item_key] = item

        return data

    def update_from_dict(self: ProtectObject, data: Dict[str, Any]) -> ProtectObject:
        """Updates current object from a cleaned UFP JSON dict"""
        data_set = set(data)
        for key in self._get_protect_objs_set().intersection(data_set):
            unifi_obj: Optional[Any] = getattr(self, key)
            if unifi_obj is not None and isinstance(unifi_obj, ProtectBaseObject):
                setattr(self, key, unifi_obj.update_from_dict(data.pop(key)))

        data = self._inject_api(data, self._api)
        unifi_lists = self._get_protect_lists()
        for key in self._get_protect_lists_set().intersection(data_set):
            if not isinstance(data[key], list):
                continue
            klass = unifi_lists[key]
            new_items = []
            for item in data.pop(key):
                if item is not None and isinstance(item, ProtectBaseObject):
                    new_items.append(item)
                elif isinstance(item, dict):
                    new_items.append(klass(**item))
            setattr(self, key, new_items)

        # Always injected above
        del data["api"]

        for key in data:
            setattr(self, key, convert_unifi_data(data[key], self.__fields__[key]))

        self._initial_data = self.dict(exclude=self._get_excluded_changed_fields())
        return self

    def get_changed(self: ProtectObject) -> Dict[str, Any]:
        return dict_diff(self._initial_data, self.dict())

    @property
    def api(self) -> ProtectApiClient:
        """
        ProtectApiClient that the UFP object was created with. If no API Client was passed in time of
        creation, will raise `BadRequest`
        """
        if self._api is None:
            raise BadRequest("API Client not initialized")

        return self._api


class ProtectModel(ProtectBaseObject):
    """
    Base class for UFP objects with a `modelKey` attr. Provides `.from_unifi_dict()` static helper method for
    automatically decoding a `modelKey` object into the correct UFP object and type
    """

    model: Optional[ModelType]

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "modelKey": "model"}

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "modelKey" in data and data["modelKey"] is None:
            del data["modelKey"]

        return data


class ProtectModelWithId(ProtectModel):
    id: str

    async def _api_update(self, data: Dict[str, Any]) -> None:
        raise NotImplementedError()

    async def save_device(self, force_emit: bool = False) -> None:
        """
        Generates a diff for unsaved changed on the device and sends them back to UFP

        USE WITH CAUTION, updates _all_ fields for the current object that have been changed.
        May have unexpected side effects.

        Tested updates have been added a methods on applicable devices.

        Args:

        * `force_emit`: Emit a fake UFP WS message. Should only be use for when UFP does not properly emit a WS message
        """

        if self.model is None:
            raise BadRequest("Unknown model type")

        new_data = self.dict(exclude=self._get_excluded_changed_fields())
        updated = self.unifi_dict(data=self.get_changed())

        # do not patch when there are no updates
        if updated == {}:
            return

        await self._api_update(updated)
        self._initial_data = new_data

        if not force_emit:
            return

        header = WSPacketFrameHeader(
            packet_type=1, payload_format=ProtectWSPayloadFormat.JSON.value, deflated=0, unknown=1, payload_size=1
        )

        action_frame = WSJSONPacketFrame()
        action_frame.header = header
        action_frame.data = {"action": "update", "newUpdateId": None, "modelKey": self.model.value, "id": self.id}

        data_frame = WSJSONPacketFrame()
        data_frame.header = header
        data_frame.data = updated

        message = self.api.bootstrap.process_ws_packet(WSPacket(action_frame.packed + data_frame.packed))
        if message is not None:
            self.api.emit_message(message)


class ProtectDeviceModel(ProtectModelWithId):
    name: str
    type: str
    mac: str
    host: Optional[IPv4Address]
    up_since: Optional[datetime]
    uptime: Optional[timedelta]
    last_seen: Optional[datetime]
    hardware_revision: Optional[str]
    firmware_version: str
    is_updating: bool
    is_ssh_enabled: bool

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "lastSeen" in data:
            data["lastSeen"] = process_datetime(data, "lastSeen")
        if "upSince" in data and data["upSince"] is not None:
            data["upSince"] = process_datetime(data, "upSince")
        if "uptime" in data and data["uptime"] is not None and not isinstance(data["uptime"], timedelta):
            data["uptime"] = timedelta(milliseconds=int(data["uptime"]))
        # hardware revisions for all devices are not simple numbers
        # so cast them all to str to be consistent
        if "hardwareRevision" in data and data["hardwareRevision"] is not None:
            data["hardwareRevision"] = str(data["hardwareRevision"])

        return super().unifi_dict_to_dict(data)


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

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "bridge": "bridgeId"}

    async def _api_update(self, data: Dict[str, Any]) -> None:
        if self.model is not None:
            return await self.api.update_device(self.model, self.id, data)

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

    @property
    def protect_url(self) -> str:
        """UFP Web app URL for this device"""

        return f"{self.api.base_url}/protect/devices/{self.id}"

    def get_changed(self) -> Dict[str, Any]:
        """Gets dictionary of all changed fields"""

        new_data = self.dict(exclude=self._get_excluded_changed_fields())
        updated = dict_diff(self._initial_data, new_data)

        return updated

    async def set_ssh(self, enabled: bool) -> None:
        """Sets ssh status for protect device"""

        self.is_ssh_enabled = enabled
        await self.save_device()

    async def reboot(self) -> None:
        """Reboots an adopted device"""

        if self.model is not None:
            await self.api.reboot_device(self.model, self.id)


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
