"""Tests for pyunifiprotect.unifi_protect_server."""

import pytest

from pyunifiprotect import ProtectApiClient


@pytest.mark.asyncio
async def test_api_client_creation():
    """Test we can create the object."""

    client = ProtectApiClient("127.0.0.1", 0, "username", "password")
    assert client


@pytest.mark.asyncio
async def test_bootstrap(protect_client: ProtectApiClient):
    """Verifies lookup of all object via ID"""

    assert protect_client.bootstrap.auth_user

    for viewer in protect_client.bootstrap.viewers.values():
        assert viewer.liveview

    for liveview in protect_client.bootstrap.liveviews.values():
        liveview.owner

        for slot in liveview.slots:
            assert len(slot.camera_ids) == len(slot.cameras)

    for user in protect_client.bootstrap.users.values():
        assert len(user.group_ids) == len(user.groups)

        if user.cloud_account is not None:
            assert user.cloud_account.user == user
