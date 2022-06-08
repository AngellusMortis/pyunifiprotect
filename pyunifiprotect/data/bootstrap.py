"""UniFi Protect Bootstrap."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional, Set, Tuple, cast
from uuid import UUID

from pydantic.fields import PrivateAttr

from pyunifiprotect.data.base import (
    RECENT_EVENT_MAX,
    ProtectBaseObject,
    ProtectModel,
    ProtectModelWithId,
)
from pyunifiprotect.data.convert import create_from_unifi_dict
from pyunifiprotect.data.devices import (
    Bridge,
    Camera,
    Chime,
    Doorlock,
    Light,
    ProtectAdoptableDeviceModel,
    Sensor,
    Viewer,
)
from pyunifiprotect.data.nvr import NVR, Event, Group, Liveview, User
from pyunifiprotect.data.types import EventType, FixSizeOrderedDict, ModelType
from pyunifiprotect.data.websocket import (
    WSAction,
    WSJSONPacketFrame,
    WSPacket,
    WSSubscriptionMessage,
)
from pyunifiprotect.utils import utc_now

_LOGGER = logging.getLogger(__name__)

MAX_SUPPORTED_CAMERAS = 256
MAX_EVENT_HISTORY_IN_STATE_MACHINE = MAX_SUPPORTED_CAMERAS * 2
STATS_KEYS = {
    "storageStats",
    "stats",
    "systemInfo",
    "phyRate",
    "wifiConnectionState",
    "upSince",
    "uptime",
    "lastSeen",
    "recordingSchedules",
    "eventStats",
}

CAMERA_EVENT_ATTR_MAP: Dict[EventType, Tuple[str, str]] = {
    EventType.MOTION: ("last_motion", "last_motion_event_id"),
    EventType.SMART_DETECT: ("last_smart_detect", "last_smart_detect_event_id"),
    EventType.RING: ("last_ring", "last_ring_event_id"),
}


def _remove_stats_keys(data: Dict[str, Any], ignore_stats: bool) -> Dict[str, Any]:
    if ignore_stats:
        for key in STATS_KEYS.intersection(data.keys()):
            del data[key]
    return data


def _process_light_event(event: Event) -> None:
    if event.light is None:
        return

    dt = event.light.last_motion
    if dt is None or event.start >= dt or (event.end is not None and event.end >= dt):
        event.light.last_motion_event_id = event.id


def _process_sensor_event(event: Event) -> None:
    if event.sensor is None:
        return

    if event.type == EventType.MOTION_SENSOR:
        dt = event.sensor.motion_detected_at
        if dt is None or event.start >= dt or (event.end is not None and event.end >= dt):
            event.sensor.last_motion_event_id = event.id
    elif event.type in (EventType.SENSOR_CLOSED, EventType.SENSOR_OPENED):
        dt = event.sensor.open_status_changed_at
        if dt is None or event.start >= dt or (event.end is not None and event.end >= dt):
            event.sensor.last_contact_event_id = event.id
    elif event.type == EventType.SENSOR_EXTREME_VALUE:
        dt = event.sensor.extreme_value_detected_at
        if dt is None or event.start >= dt or (event.end is not None and event.end >= dt):
            event.sensor.extreme_value_detected_at = event.end
            event.sensor.last_value_event_id = event.id
    elif event.type == EventType.SENSOR_ALARM:
        dt = event.sensor.alarm_triggered_at
        if dt is None or event.start >= dt or (event.end is not None and event.end >= dt):
            event.sensor.last_value_event_id = event.id


def _process_camera_event(event: Event) -> None:
    if event.camera is None:
        return

    dt_attr, event_attr = CAMERA_EVENT_ATTR_MAP[event.type]
    dt = getattr(event.camera, dt_attr)
    if dt is None or event.start >= dt or (event.end is not None and event.end >= dt):
        setattr(event.camera, event_attr, event.id)


@dataclass
class WSStat:
    model: str
    action: str
    keys: List[str]
    keys_set: List[str]
    size: int
    filtered: bool


class ProtectDeviceRef(ProtectBaseObject):
    model: ModelType
    id: str


class Bootstrap(ProtectBaseObject):
    auth_user_id: str
    access_key: str
    cameras: Dict[str, Camera]
    users: Dict[str, User]
    groups: Dict[str, Group]
    liveviews: Dict[str, Liveview]
    nvr: NVR
    viewers: Dict[str, Viewer]
    lights: Dict[str, Light]
    bridges: Dict[str, Bridge]
    sensors: Dict[str, Sensor]
    doorlocks: Dict[str, Doorlock]
    chimes: Dict[str, Chime]
    last_update_id: UUID

    # TODO:
    # legacyUFVs
    # displays
    # schedules

    # not directly from UniFi
    events: Dict[str, Event] = FixSizeOrderedDict()
    capture_ws_stats: bool = False
    mac_lookup: dict[str, ProtectDeviceRef] = {}
    _ws_stats: List[WSStat] = PrivateAttr([])
    _has_doorbell: Optional[bool] = PrivateAttr(None)
    _has_smart: Optional[bool] = PrivateAttr(None)
    _recording_start: Optional[datetime] = PrivateAttr(None)

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        api = cls._get_api(data.get("api"))
        data["macLookup"] = {}
        for model_type in ModelType.bootstrap_models():
            key = model_type + "s"
            items: Dict[str, ProtectModel] = {}
            for item in data[key]:
                if api is not None and api.ignore_unadopted and not item.get("isAdopted", True):
                    continue

                items[item["id"]] = item
                if "mac" in item:
                    cleaned_mac = item["mac"].lower().replace(":", "")
                    data["macLookup"][cleaned_mac] = {"model": model_type, "id": item["id"]}
            data[key] = items

        return super().unifi_dict_to_dict(data)

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "events" in data:
            del data["events"]
        if "captureWsStats" in data:
            del data["captureWsStats"]
        if "macLookup" in data:
            del data["macLookup"]

        for model_type in ModelType.bootstrap_models():
            attr = model_type + "s"
            if attr in data and isinstance(data[attr], dict):
                data[attr] = list(data[attr].values())

        return data

    @property
    def ws_stats(self) -> List[WSStat]:
        return self._ws_stats

    def clear_ws_stats(self) -> None:
        self._ws_stats = []

    @property
    def auth_user(self) -> User:
        user: User = self.api.bootstrap.users[self.auth_user_id]
        return user

    @property
    def has_doorbell(self) -> bool:
        if self._has_doorbell is None:
            self._has_doorbell = any(c.feature_flags.has_chime for c in self.cameras.values())

        return self._has_doorbell

    @property
    def recording_start(self) -> datetime:
        if self._recording_start is None:
            self._recording_start = min(
                c.stats.video.recording_start
                for c in self.cameras.values()
                if c.stats.video.recording_start is not None
            )
        return self._recording_start

    @property
    def has_smart_detections(self) -> bool:
        if self._has_smart is None:
            self._has_smart = any(c.feature_flags.has_smart_detect for c in self.cameras.values())
        return self._has_smart

    def get_device_from_mac(self, mac: str) -> ProtectAdoptableDeviceModel | None:
        """Retrieve a device from MAC address"""

        mac = mac.lower().replace(":", "").replace("-", "").replace("_", "")
        ref = self.mac_lookup.get(mac)
        if ref is None:
            return None

        devices = getattr(self, f"{ref.model}s")
        return cast(ProtectAdoptableDeviceModel, devices.get(ref.id))

    def process_event(self, event: Event) -> None:
        if event.type in CAMERA_EVENT_ATTR_MAP and event.camera is not None:
            _process_camera_event(event)
        elif event.type == EventType.MOTION_LIGHT and event.light is not None:
            _process_light_event(event)
        elif event.type == EventType.MOTION_SENSOR and event.sensor is not None:
            _process_sensor_event(event)

        self.events[event.id] = event

    def _create_stat(self, packet: WSPacket, keys_set: List[str], filtered: bool) -> None:
        if self.capture_ws_stats:
            self._ws_stats.append(
                WSStat(
                    model=packet.action_frame.data["modelKey"],
                    action=packet.action_frame.data["action"],
                    keys=list(packet.data_frame.data.keys()),
                    keys_set=keys_set,
                    size=len(packet.raw),
                    filtered=filtered,
                )
            )

    def _get_frame_data(self, packet: WSPacket) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if self.capture_ws_stats:
            return deepcopy(packet.action_frame.data), deepcopy(packet.data_frame.data)
        return packet.action_frame.data, packet.data_frame.data

    def _process_add_packet(self, packet: WSPacket, data: Dict[str, Any]) -> Optional[WSSubscriptionMessage]:
        obj = create_from_unifi_dict(data, api=self._api)

        if isinstance(obj, Event):
            self.process_event(obj)
        elif isinstance(obj, NVR):
            self.nvr = obj
        elif (
            isinstance(obj, ProtectModelWithId)
            and obj.model is not None
            and obj.model.value in ModelType.bootstrap_models()
        ):
            key = obj.model.value + "s"
            getattr(self, key)[obj.id] = obj
        else:
            _LOGGER.debug("Unexpected bootstrap model type for add: %s", obj.model)
            return None

        updated = obj.dict()
        self._create_stat(packet, list(updated.keys()), False)
        return WSSubscriptionMessage(
            action=WSAction.ADD, new_update_id=self.last_update_id, changed_data=updated, new_obj=obj
        )

    def _process_nvr_update(
        self, packet: WSPacket, data: Dict[str, Any], ignore_stats: bool
    ) -> Optional[WSSubscriptionMessage]:
        data = _remove_stats_keys(data, ignore_stats)
        # nothing left to process
        if len(data) == 0:
            self._create_stat(packet, [], True)
            return None

        data = self.nvr.unifi_dict_to_dict(data)
        old_nvr = self.nvr.copy()
        self.nvr = self.nvr.update_from_dict(deepcopy(data))

        self._create_stat(packet, list(data.keys()), False)
        return WSSubscriptionMessage(
            action=WSAction.UPDATE,
            new_update_id=self.last_update_id,
            changed_data=data,
            new_obj=self.nvr,
            old_obj=old_nvr,
        )

    def _process_device_update(
        self, packet: WSPacket, action: Dict[str, Any], data: Dict[str, Any], ignore_stats: bool
    ) -> Optional[WSSubscriptionMessage]:
        model_type = action["modelKey"]

        data = _remove_stats_keys(data, ignore_stats)
        # nothing left to process
        if len(data) == 0:
            self._create_stat(packet, [], True)
            return None

        key = model_type + "s"
        devices = getattr(self, key)
        if action["id"] in devices:
            obj: ProtectModelWithId = devices[action["id"]]
            data = obj.unifi_dict_to_dict(data)
            old_obj = obj.copy()
            obj = obj.update_from_dict(deepcopy(data))
            now = utc_now()

            if isinstance(obj, Event):
                self.process_event(obj)
            elif isinstance(obj, Camera):
                if "last_ring" in data and obj.last_ring:
                    is_recent = obj.last_ring + RECENT_EVENT_MAX >= now
                    _LOGGER.debug("last_ring for %s (%s)", obj.id, is_recent)
                    if is_recent:
                        obj.set_ring_timeout()
            elif isinstance(obj, Sensor):
                if "alarm_triggered_at" in data and obj.alarm_triggered_at:
                    is_recent = obj.alarm_triggered_at + RECENT_EVENT_MAX >= now
                    _LOGGER.debug("alarm_triggered_at for %s (%s)", obj.id, is_recent)
                    if is_recent:
                        obj.set_alarm_timeout()

            devices[action["id"]] = obj

            self._create_stat(packet, list(data.keys()), False)
            return WSSubscriptionMessage(
                action=WSAction.UPDATE,
                new_update_id=self.last_update_id,
                changed_data=data,
                new_obj=obj,
                old_obj=old_obj,
            )

        # ignore updates to events that phase out
        if model_type != ModelType.EVENT.value:
            _LOGGER.debug("Unexpected %s: %s", key, action["id"])
        return None

    def process_ws_packet(
        self, packet: WSPacket, models: Optional[Set[ModelType]] = None, ignore_stats: bool = False
    ) -> Optional[WSSubscriptionMessage]:
        if models is None:
            models = set()

        if not isinstance(packet.action_frame, WSJSONPacketFrame):
            _LOGGER.debug("Unexpected action frame format: %s", packet.action_frame.payload_format)

        if not isinstance(packet.data_frame, WSJSONPacketFrame):
            _LOGGER.debug("Unexpected data frame format: %s", packet.data_frame.payload_format)

        action, data = self._get_frame_data(packet)
        if action["newUpdateId"] is not None:
            self.last_update_id = UUID(action["newUpdateId"])

        if action["modelKey"] not in ModelType.values():
            _LOGGER.debug("Unknown model type: %s", action["modelKey"])
            self._create_stat(packet, [], True)
            return None

        if len(models) > 0 and ModelType(action["modelKey"]) not in models or len(data) == 0:
            self._create_stat(packet, [], True)
            return None

        if action["action"] == "add":
            return self._process_add_packet(packet, data)

        if action["action"] == "update":
            if action["modelKey"] == ModelType.NVR.value:
                return self._process_nvr_update(packet, data, ignore_stats)
            if action["modelKey"] in ModelType.bootstrap_models() or action["modelKey"] == ModelType.EVENT.value:
                return self._process_device_update(packet, action, data, ignore_stats)
            _LOGGER.debug("Unexpected bootstrap model type for update: %s", action["modelKey"])

        self._create_stat(packet, [], True)
        return None
