"""Unifi Protect Data Conversion."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Final, Optional, Type, cast

from pyunifiprotect.data.devices import Bridge, Camera, Light, Sensor, Viewer
from pyunifiprotect.data.nvr import (
    NVR,
    CloudAccount,
    Event,
    Group,
    Liveview,
    User,
    UserLocation,
)
from pyunifiprotect.data.types import ModelType
from pyunifiprotect.exceptions import DataDecodeError

if TYPE_CHECKING:
    from pyunifiprotect.data.base import ProtectModel
    from pyunifiprotect.unifi_protect_server import ProtectApiClient


MODEL_TO_CLASS: Final = {
    ModelType.EVENT: Event,
    ModelType.GROUP: Group,
    ModelType.USER_LOCATION: UserLocation,
    ModelType.CLOUD_IDENTITY: CloudAccount,
    ModelType.USER: User,
    ModelType.NVR: NVR,
    ModelType.LIGHT: Light,
    ModelType.CAMERA: Camera,
    ModelType.LIVEVIEW: Liveview,
    ModelType.VIEWPORT: Viewer,
    ModelType.BRIDGE: Bridge,
    ModelType.SENSOR: Sensor,
}


def get_klass_from_dict(data: Dict[str, Any]) -> Type[ProtectModel]:
    """
    Helper method to read the `modelKey` from a UFP JSON dict and get the correct Python class for conversion.
    Will raise `DataDecodeError` if the `modelKey` is for an unknown object.
    """
    if "modelKey" not in data:
        raise DataDecodeError("No modelKey")

    model = ModelType(data["modelKey"])

    klass = MODEL_TO_CLASS.get(model)

    if klass is None:
        raise DataDecodeError("Unknown modelKey")

    return cast(Type[ProtectModel], klass)


def create_from_unifi_dict(
    data: Dict[str, Any], api: Optional[ProtectApiClient] = None, klass: Optional[Type[ProtectModel]] = None
) -> ProtectModel:
    """
    Helper method to read the `modelKey` from a UFP JSON dict and convert to currect Python class.
    Will raise `DataDecodeError` if the `modelKey` is for an unknown object.
    """

    if "modelKey" not in data:
        raise DataDecodeError("No modelKey")

    if klass is None:
        klass = get_klass_from_dict(data)

    return klass.from_unifi_dict(**data, api=api)
