import enum
from typing import List, Optional

from pydantic import ConstrainedDecimal, ConstrainedInt


class FixSizeOrderedDict(dict):
    """A fixed size ordered dict."""

    def __init__(self, *args, max_size=0, **kwargs):
        """Create the FixSizeOrderedDict."""
        self._max_size = max_size
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        """Set an update up to the max size."""
        dict.__setitem__(self, key, value)
        if self._max_size > 0 and len(self) > 0 and len(self) > self._max_size:
            del self[list(self.keys())[0]]


class ValuesEnumMixin:
    _values: Optional[List[str]] = None

    @classmethod
    def values(cls) -> List[str]:
        if cls._values is None:
            cls._values = [e.value for e in cls]  # type: ignore
        return cls._values


@enum.unique
class ModelType(str, ValuesEnumMixin, enum.Enum):
    CAMERA = "camera"
    CLOUD_IDENTITY = "cloudIdentity"
    EVENT = "event"
    GROUP = "group"
    LIGHT = "light"
    LIVEVIEW = "liveview"
    NVR = "nvr"
    USER = "user"
    USER_LOCATION = "userLocation"
    VIEWPORT = "viewer"
    DISPLAYS = "display"
    BRIDGE = "bridge"
    SENSOR = "sensor"
    DOORLOCK = "doorlock"
    SCHEDULE = "schedule"
    CHIME = "chime"

    @staticmethod
    def bootstrap_models() -> List[str]:
        # TODO:
        # legacyUFV
        # display
        # sensor
        # doorlock

        return [
            ModelType.CAMERA.value,
            ModelType.USER.value,
            ModelType.GROUP.value,
            ModelType.LIVEVIEW.value,
            ModelType.VIEWPORT.value,
            ModelType.LIGHT.value,
            ModelType.BRIDGE.value,
        ]


@enum.unique
class EventType(str, ValuesEnumMixin, enum.Enum):
    SMART_DETECT = "smartDetectZone"
    MOTION = "motion"
    RING = "ring"
    DISCONNECT = "disconnect"
    PROVISION = "provision"
    ACCESS = "access"
    OFFLINE = "offline"
    OFF = "off"
    UPDATE = "update"
    CAMERA_POWER_CYCLE = "cameraPowerCycling"
    VIDEO_EXPORTED = "videoExported"

    @staticmethod
    def device_events() -> List[str]:
        return [EventType.MOTION.value, EventType.RING.value, EventType.SMART_DETECT.value]

    @staticmethod
    def motion_events() -> List[str]:
        return [EventType.MOTION.value, EventType.SMART_DETECT.value]


@enum.unique
class StateType(str, enum.Enum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"


@enum.unique
class ProtectWSPayloadFormat(int, enum.Enum):
    """Websocket Payload formats."""

    JSON = 1
    UTF8String = 2
    NodeBuffer = 3


@enum.unique
class SmartDetectObjectType(str, enum.Enum):
    PERSON = "person"
    VEHICLE = "vehicle"


@enum.unique
class DoorbellMessageType(str, enum.Enum):
    LEAVE_PACKAGE_AT_DOOR = "LEAVE_PACKAGE_AT_DOOR"
    DO_NOT_DISTURB = "DO_NOT_DISTURB"
    CUSTOM_MESSAGE = "CUSTOM_MESSAGE"


@enum.unique
class LightModeEnableType(str, enum.Enum):
    DARK = "dark"
    ALWAYS = "fulltime"


@enum.unique
class LightModeType(str, enum.Enum):
    MOTION = "motion"
    WHEN_DARK = "always"
    MANUAL = "off"


@enum.unique
class VideoMode(str, enum.Enum):
    DEFAULT = "default"
    HIGH_FPS = "highFps"


@enum.unique
class RecordingMode(str, enum.Enum):
    ALWAYS = "always"
    NEVER = "never"
    DETECTIONS = "detections"


class LEDLevel(ConstrainedInt):
    ge = 1
    le = 6


class PercentInt(ConstrainedInt):
    ge = 0
    le = 100


class Percent(ConstrainedDecimal):
    ge = 0
    le = 1
    max_digits = 4
    decimal_places = 3
