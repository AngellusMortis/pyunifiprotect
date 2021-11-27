"""Unifi Protect Bootstrap."""
from __future__ import annotations

from copy import deepcopy
import logging
from typing import Any, Dict, Optional, Set, Tuple
from uuid import UUID

from pyunifiprotect.data.base import ProtectBaseObject, ProtectModel, ProtectModelWithId
from pyunifiprotect.data.convert import create_from_unifi_dict
from pyunifiprotect.data.devices import Bridge, Camera, Light, Sensor, Viewer
from pyunifiprotect.data.nvr import NVR, Event, Group, Liveview, User
from pyunifiprotect.data.types import EventType, FixSizeOrderedDict, ModelType
from pyunifiprotect.data.websocket import (
    WSAction,
    WSJSONPacketFrame,
    WSPacket,
    WSSubscriptionMessage,
)

_LOGGER = logging.getLogger(__name__)

MAX_SUPPORTED_CAMERAS = 256
MAX_EVENT_HISTORY_IN_STATE_MACHINE = MAX_SUPPORTED_CAMERAS * 2

EVENT_ATTR_MAP: Dict[EventType, Tuple[str, str]] = {
    EventType.MOTION: ("last_motion", "last_motion_event_id"),
    EventType.SMART_DETECT: ("last_smart_detect", "last_smart_detect_event_id"),
    EventType.RING: ("last_ring", "last_ring_event_id"),
}


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
    last_update_id: UUID

    # TODO:
    # legacyUFVs
    # displays
    # doorlocks
    # chimes
    # schedules

    # not directly from Unifi
    events: Dict[str, Event] = FixSizeOrderedDict()

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        for model_type in ModelType.bootstrap_models():
            key = model_type + "s"
            items: Dict[str, ProtectModel] = {}
            for item in data[key]:
                items[item["id"]] = item
            data[key] = items

        return super().unifi_dict_to_dict(data)

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "events" in data:
            del data["events"]

        for model_type in ModelType.bootstrap_models():
            attr = model_type + "s"
            if attr in data and isinstance(data[attr], dict):
                data[attr] = list(data[attr].values())

        return data

    @property
    def auth_user(self) -> User:
        user: User = self.api.bootstrap.users[self.auth_user_id]
        return user

    def process_event(self, event: Event) -> None:
        if event.camera is None:
            return

        if event.type in EVENT_ATTR_MAP:
            dt_attr, event_attr = EVENT_ATTR_MAP[event.type]
            dt = getattr(event.camera, dt_attr)
            if dt is None or event.start >= dt or (event.end is not None and event.end >= dt):
                setattr(event.camera, event_attr, event.id)

        self.events[event.id] = event

    def process_ws_packet(self, packet: WSPacket) -> Optional[WSSubscriptionMessage]:
        if not isinstance(packet.action_frame, WSJSONPacketFrame):
            _LOGGER.debug("Unexpected action frame format: %s", packet.action_frame.payload_format)

        if not isinstance(packet.data_frame, WSJSONPacketFrame):
            _LOGGER.debug("Unexpected data frame format: %s", packet.data_frame.payload_format)

        action: dict = packet.action_frame.data  # type: ignore
        data: dict = packet.data_frame.data  # type: ignore
        if action["newUpdateId"] is not None:
            self.last_update_id = UUID(action["newUpdateId"])

        if action["modelKey"] not in ModelType.values():
            _LOGGER.debug("Unknown model type: %s", action["modelKey"])
            return None

        if action["action"] == "add":
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

            return WSSubscriptionMessage(
                action=WSAction.ADD, new_update_id=self.last_update_id, changed_data=obj.dict(), new_obj=obj
            )

        if action["action"] == "update":
            model_type = action["modelKey"]
            if model_type == ModelType.NVR.value:
                data = self.nvr.unifi_dict_to_dict(data)
                old_nvr = self.nvr.copy()
                self.nvr = self.nvr.update_from_dict(deepcopy(data))

                return WSSubscriptionMessage(
                    action=WSAction.UPDATE,
                    new_update_id=self.last_update_id,
                    changed_data=data,
                    new_obj=self.nvr,
                    old_obj=old_nvr,
                )
            if model_type in ModelType.bootstrap_models() or model_type == ModelType.EVENT.value:
                key = model_type + "s"
                devices = getattr(self, key)
                if action["id"] in devices:
                    obj: ProtectModel = devices[action["id"]]
                    data = obj.unifi_dict_to_dict(data)
                    old_obj = obj.copy()
                    obj = obj.update_from_dict(deepcopy(data))

                    if isinstance(obj, Event):
                        self.process_event(obj)

                    devices[action["id"]] = obj

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
            else:
                _LOGGER.debug("Unexpected bootstrap model type for update: %s", model_type)

        return None
