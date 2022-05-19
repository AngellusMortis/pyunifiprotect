# type: ignore
# pylint: disable=protected-access

from typing import Optional

from pydantic.error_wrappers import ValidationError
import pytest

from pyunifiprotect.data import Camera
from pyunifiprotect.data.devices import Chime
from pyunifiprotect.exceptions import BadRequest
from tests.conftest import TEST_CAMERA_EXISTS, TEST_CHIME_EXISTS


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.parametrize("level", [-1, 0, 100, 200])
@pytest.mark.asyncio
async def test_chime_set_volume(chime_obj: Optional[Chime], level: int):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")

    chime_obj.api.api_request.reset_mock()
    chime_obj.volume = 20
    chime_obj._initial_data = chime_obj.dict()

    if level in (-1, 200):
        with pytest.raises(ValidationError):
            await chime_obj.set_volume(level)

        assert not chime_obj.api.api_request.called
    else:
        await chime_obj.set_volume(level)

        chime_obj.api.api_request.assert_called_with(
            f"chimes/{chime_obj.id}",
            method="patch",
            json={"volume": level},
        )


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_chime_play(chime_obj: Optional[Chime]):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")

    await chime_obj.play()

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}/play-speaker",
        method="post",
    )


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_chime_play_buzzer(chime_obj: Optional[Chime]):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")

    await chime_obj.play_buzzer()

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}/play-buzzer",
        method="post",
    )


@pytest.mark.skipif(not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_chime_add_camera(chime_obj: Optional[Chime], camera_obj: Optional[Camera]):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.api.api_request.reset_mock()
    chime_obj.camera_ids = []
    chime_obj._initial_data = chime_obj.dict()

    camera_obj.api.api_request.reset_mock()
    camera_obj.feature_flags.has_chime = True
    camera_obj._initial_data = chime_obj.dict()

    await chime_obj.add_camera(camera_obj)

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}",
        method="patch",
        json={"cameraIds": [camera_obj.id]},
    )


@pytest.mark.skipif(not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_chime_add_camera_not_doorbell(chime_obj: Optional[Chime], camera_obj: Optional[Camera]):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.api.api_request.reset_mock()
    chime_obj.camera_ids = []
    chime_obj._initial_data = chime_obj.dict()

    camera_obj.api.api_request.reset_mock()
    camera_obj.feature_flags.has_chime = False
    camera_obj._initial_data = chime_obj.dict()

    with pytest.raises(BadRequest):
        await chime_obj.add_camera(camera_obj)

    assert not chime_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_chime_add_camera_exists(chime_obj: Optional[Chime], camera_obj: Optional[Camera]):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.api.api_request.reset_mock()
    chime_obj.camera_ids = [camera_obj.id]
    chime_obj._initial_data = chime_obj.dict()

    camera_obj.api.api_request.reset_mock()
    camera_obj.feature_flags.has_chime = True
    camera_obj._initial_data = chime_obj.dict()

    with pytest.raises(BadRequest):
        await chime_obj.add_camera(camera_obj)

    assert not chime_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_chime_remove_camera(chime_obj: Optional[Chime], camera_obj: Optional[Camera]):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.api.api_request.reset_mock()
    chime_obj.camera_ids = [camera_obj.id]
    chime_obj._initial_data = chime_obj.dict()

    camera_obj.api.api_request.reset_mock()
    camera_obj.feature_flags.has_chime = True
    camera_obj._initial_data = chime_obj.dict()

    await chime_obj.remove_camera(camera_obj)

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}",
        method="patch",
        json={"cameraIds": []},
    )


@pytest.mark.skipif(not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio
async def test_chime_remove_camera_not_exists(chime_obj: Optional[Chime], camera_obj: Optional[Camera]):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.api.api_request.reset_mock()
    chime_obj.camera_ids = []
    chime_obj._initial_data = chime_obj.dict()

    camera_obj.api.api_request.reset_mock()
    camera_obj.feature_flags.has_chime = True
    camera_obj._initial_data = chime_obj.dict()

    with pytest.raises(BadRequest):
        await chime_obj.remove_camera(camera_obj)

    assert not chime_obj.api.api_request.called
