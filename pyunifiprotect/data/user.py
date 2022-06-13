"""UniFi Protect User models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Set, cast

from pydantic.fields import PrivateAttr

from pyunifiprotect.data.base import ProtectBaseObject, ProtectModel, ProtectModelWithId
from pyunifiprotect.data.types import ModelType, PermissionNode


class Permission(ProtectBaseObject):
    raw_permission: str
    model: ModelType
    nodes: Set[PermissionNode]
    obj_id: Optional[str]

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        permission = data.get("rawPermission", "")
        parts = permission.split(":")
        if len(parts) < 2:
            raise ValueError(f"Invalid permission: {permission}")

        data["model"] = ModelType(parts[0])
        if parts[1] == "*":
            data["nodes"] = list(PermissionNode)
        else:
            data["nodes"] = [PermissionNode(n) for n in parts[1].split(",")]

        if len(parts) == 3 and parts[2] != "*" and parts[2] != "$":
            data["obj_id"] = parts[2]

        return super().unifi_dict_to_dict(data)

    def unifi_dict(  # type: ignore
        self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None
    ) -> str:
        return self.raw_permission

    @property
    def obj(self) -> Optional[ProtectModel]:
        if self.obj_id is None:
            return None

        devices = getattr(self.api.bootstrap, f"{self.model.value}s")
        return cast(Optional[ProtectModel], devices.get(self.obj_id))


class Group(ProtectModelWithId):
    name: str
    permissions: List[Permission]
    type: str
    is_default: bool

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "permissions" in data:
            permissions = data.pop("permissions")
            data["permissions"] = [{"rawPermission": p} for p in permissions]

        return super().unifi_dict_to_dict(data)


class UserLocation(ProtectModel):
    is_away: bool
    latitude: Optional[float]
    longitude: Optional[float]


class CloudAccount(ProtectModelWithId):
    first_name: str
    last_name: str
    email: str
    user_id: str
    name: str
    location: Optional[UserLocation]
    profile_img: Optional[str] = None

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "user": "userId"}

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        # id and cloud ID are always the same
        if "id" in data:
            data["cloudId"] = data["id"]
        if "location" in data and data["location"] is None:
            del data["location"]

        return data

    @property
    def user(self) -> User:
        return self.api.bootstrap.users[self.user_id]


class UserFeatureFlags(ProtectBaseObject):
    notifications_v2: bool


class User(ProtectModelWithId):
    permissions: List[Permission]
    last_login_ip: Optional[str]
    last_login_time: Optional[datetime]
    is_owner: bool
    enable_notifications: bool
    has_accepted_invite: bool
    all_permissions: List[Permission]
    scopes: Optional[List[str]] = None
    location: Optional[UserLocation]
    name: str
    first_name: str
    last_name: str
    email: str
    local_username: str
    group_ids: List[str]
    cloud_account: Optional[CloudAccount]
    feature_flags: UserFeatureFlags

    # TODO:
    # settings
    # alertRules
    # notificationsV2

    _groups: Optional[List[Group]] = PrivateAttr(None)
    _perm_cache: Dict[str, bool] = PrivateAttr({})

    def __init__(self, **data: Any) -> None:
        if "permissions" in data:
            permissions = data.pop("permissions")
            data["permissions"] = [{"raw_permission": p} if isinstance(p, str) else p for p in permissions]
        if "allPermissions" in data:
            permissions = data.pop("allPermissions")
            data["allPermissions"] = [{"raw_permission": p} if isinstance(p, str) else p for p in permissions]

        super().__init__(**data)

    @classmethod
    def unifi_dict_to_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if "permissions" in data:
            permissions = data.pop("permissions")
            data["permissions"] = [{"rawPermission": p} for p in permissions]
        if "allPermissions" in data:
            permissions = data.pop("allPermissions")
            data["allPermissions"] = [{"rawPermission": p} for p in permissions]

        return super().unifi_dict_to_dict(data)

    @classmethod
    def _get_unifi_remaps(cls) -> Dict[str, str]:
        return {**super()._get_unifi_remaps(), "groups": "groupIds"}

    def unifi_dict(self, data: Optional[Dict[str, Any]] = None, exclude: Optional[Set[str]] = None) -> Dict[str, Any]:
        data = super().unifi_dict(data=data, exclude=exclude)

        if "location" in data and data["location"] is None:
            del data["location"]

        return data

    @property
    def groups(self) -> List[Group]:
        """
        Groups the user is in

        Will always be empty if the user only has read only access.
        """

        if self._groups is not None:
            return self._groups

        self._groups = [self.api.bootstrap.groups[g] for g in self.group_ids if g in self.api.bootstrap.groups]
        return self._groups

    def can(self, model: ModelType, node: PermissionNode, obj: Optional[ProtectModel] = None) -> bool:
        """Checks if a user can do a specific action"""

        perm_str = f"{model.value}:{node.value}:{obj if obj is not None else '*'}"
        if perm_str in self._perm_cache:
            return self._perm_cache[perm_str]

        for perm in self.all_permissions:
            if model != perm.model or node not in perm.nodes:
                continue
            if perm.obj_id is None:
                self._perm_cache[perm_str] = True
                return True
            if perm.obj_id is not None and perm.obj == obj:
                self._perm_cache[perm_str] = True
                return True
        self._perm_cache[perm_str] = False
        return False
