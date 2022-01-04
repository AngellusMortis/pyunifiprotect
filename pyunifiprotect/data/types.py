from __future__ import annotations

import enum
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Generic,
    List,
    Literal,
    Optional,
    TypeVar,
    Union,
)

from packaging.version import Version as BaseVersion
from pydantic import ConstrainedDecimal, ConstrainedInt
from pydantic.color import Color as BaseColor
from pydantic.types import ConstrainedStr

KT = TypeVar("KT")
VT = TypeVar("VT")


# TODO: Remove when 3.8 support is dropped
if TYPE_CHECKING:

    class FixSizeOrderedDictBase(dict[KT, VT]):
        pass

else:

    class FixSizeOrderedDictBase(Generic[KT, VT], dict):
        pass


DEFAULT = "DEFAULT_VALUE"
DEFAULT_TYPE = Literal["DEFAULT_VALUE"]


class FixSizeOrderedDict(FixSizeOrderedDictBase[KT, VT]):
    """A fixed size ordered dict."""

    def __init__(self, *args: Any, max_size: int = 0, **kwargs: Any) -> None:
        """Create the FixSizeOrderedDict."""
        self._max_size = max_size
        super().__init__(*args, **kwargs)

    def __setitem__(self, key: KT, value: VT) -> None:
        """Set an update up to the max size."""
        dict.__setitem__(self, key, value)
        if self._max_size > 0 and len(self) > 0 and len(self) > self._max_size:
            del self[list(self.keys())[0]]


class ValuesEnumMixin:
    _values: Optional[List[str]] = None
    _values_normalized: Optional[Dict[str, str]] = None

    @classmethod
    def values(cls) -> List[str]:
        if cls._values is None:
            cls._values = [e.value for e in cls]  # type: ignore
        return cls._values

    @classmethod
    def _missing_(cls, value: Any) -> Optional[Any]:
        if cls._values_normalized is None:
            cls._values_normalized = {e.value.lower(): e for e in cls}  # type: ignore

        value_normal = value
        if isinstance(value, str):
            value_normal = value.lower()
        return cls._values_normalized.get(value_normal)


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
        # doorlock

        return [
            ModelType.CAMERA.value,
            ModelType.USER.value,
            ModelType.GROUP.value,
            ModelType.LIVEVIEW.value,
            ModelType.VIEWPORT.value,
            ModelType.LIGHT.value,
            ModelType.BRIDGE.value,
            ModelType.SENSOR.value,
        ]


@enum.unique
class EventType(str, ValuesEnumMixin, enum.Enum):
    ACCESS = "access"
    APP_UPDATE = "applicationUpdate"
    CAMERA_POWER_CYCLE = "cameraPowerCycling"
    DEVICE_PASSWORD_UPDATE = "devicesPasswordUpdated"
    DISCONNECT = "disconnect"
    FIRMWARE_UPDATE = "fwUpdate"
    INSTALLED_DISK = "installed"
    MOTION = "motion"
    MOTION_LIGHT = "lightMotion"
    MOTION_SENSOR = "sensorMotion"
    OFF = "off"
    OFFLINE = "offline"
    PROVISION = "provision"
    RING = "ring"
    SMART_DETECT = "smartDetectZone"
    UPDATE = "update"
    VIDEO_EXPORTED = "videoExported"
    DEVICE_ADOPTED = "deviceAdopted"
    DEVICE_UNADOPTED = "deviceUnadopted"
    RECORDING_MODE_CHANGED = "recordingModeChanged"
    SENSOR_OPENED = "sensorOpened"
    SENSOR_CLOSED = "sensorClosed"
    SENSOR_EXTREME_VALUE = "sensorExtremeValues"
    SENSOR_ALARM = "sensorAlarm"

    @staticmethod
    def device_events() -> List[str]:
        return [EventType.MOTION.value, EventType.RING.value, EventType.SMART_DETECT.value]

    @staticmethod
    def motion_events() -> List[str]:
        return [EventType.MOTION.value, EventType.SMART_DETECT.value]


@enum.unique
class StateType(str, ValuesEnumMixin, enum.Enum):
    CONNECTED = "CONNECTED"
    CONNECTING = "CONNECTING"
    DISCONNECTED = "DISCONNECTED"


@enum.unique
class ProtectWSPayloadFormat(int, enum.Enum):
    """Websocket Payload formats."""

    JSON = 1
    UTF8String = 2
    NodeBuffer = 3


@enum.unique
class SmartDetectObjectType(str, ValuesEnumMixin, enum.Enum):
    PERSON = "person"
    VEHICLE = "vehicle"
    FACE = "face"


@enum.unique
class DoorbellMessageType(str, ValuesEnumMixin, enum.Enum):
    LEAVE_PACKAGE_AT_DOOR = "LEAVE_PACKAGE_AT_DOOR"
    DO_NOT_DISTURB = "DO_NOT_DISTURB"
    CUSTOM_MESSAGE = "CUSTOM_MESSAGE"


@enum.unique
class LightModeEnableType(str, ValuesEnumMixin, enum.Enum):
    DARK = "dark"
    ALWAYS = "fulltime"


@enum.unique
class LightModeType(str, ValuesEnumMixin, enum.Enum):
    MOTION = "motion"
    WHEN_DARK = "always"
    MANUAL = "off"


@enum.unique
class VideoMode(str, ValuesEnumMixin, enum.Enum):
    DEFAULT = "default"
    HIGH_FPS = "highFps"
    # should only be for unadopted devices
    UNKNOWN = "unknown"


@enum.unique
class RecordingMode(str, ValuesEnumMixin, enum.Enum):
    ALWAYS = "always"
    NEVER = "never"
    DETECTIONS = "detections"


@enum.unique
class RecordingType(str, ValuesEnumMixin, enum.Enum):
    TIMELAPSE = "timelapse"
    CONTINUOUS = "rotating"
    DETECTIONS = "detections"


@enum.unique
class ResolutionStorageType(str, ValuesEnumMixin, enum.Enum):
    UHD = "4K"
    HD = "HD"
    FREE = "free"


@enum.unique
class IRLEDMode(str, ValuesEnumMixin, enum.Enum):
    AUTO = "auto"
    ON = "on"
    AUTO_NO_LED = "autoFilterOnly"
    OFF = "off"


@enum.unique
class MountType(str, ValuesEnumMixin, enum.Enum):
    NONE = "none"
    LEAK = "leak"
    DOOR = "door"
    WINDOW = "window"
    GARAGE = "garage"


@enum.unique
class SensorType(str, ValuesEnumMixin, enum.Enum):
    TEMPERATURE = "temperature"
    LIGHT = "light"
    HUMIDITY = "humidity"


@enum.unique
class SensorStatusType(str, ValuesEnumMixin, enum.Enum):
    UNKNOWN = "unknown"
    NEUTRAL = "neutral"
    LOW = "low"
    HIGH = "high"


class DoorbellText(ConstrainedStr):
    max_length = 30


class LEDLevel(ConstrainedInt):
    ge = 0
    le = 6


class PercentInt(ConstrainedInt):
    ge = 0
    le = 100


class ChimeDuration(ConstrainedInt):
    ge = 0
    le = 10000


class WDRLevel(ConstrainedInt):
    ge = 0
    le = 3


class Percent(ConstrainedDecimal):
    ge = 0
    le = 1
    max_digits = 4
    decimal_places = 3


CoordType = Union[Percent, int, float]


class Color(BaseColor):
    def __eq__(self, o: Any) -> bool:
        if isinstance(o, Color):
            return self.as_hex() == o.as_hex()

        return super().__eq__(o)


class Version(BaseVersion):
    def __str__(self) -> str:
        super_str = super().__str__()
        if self.pre is not None and self.pre[0] == "b":
            super_str = super_str.replace("b", "-beta.")
        return super_str
