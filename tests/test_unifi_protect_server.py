"""Tests for pyunifi_protect_server."""

import aiohttp
import pytest

from .unifi_protect_server import UpvServer


@pytest.mark.asyncio
async def test_upvserver_creation():
    """Test we can create the object."""

    upv = UpvServer(aiohttp.ClientSession(), "127.0.0.1", 0, "username", "password")
    assert upv
