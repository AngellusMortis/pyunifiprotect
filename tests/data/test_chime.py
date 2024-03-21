# mypy: disable-error-code="attr-defined, dict-item, assignment, union-attr"

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import pytest

from pyunifiprotect.data import RingSetting
from pyunifiprotect.exceptions import BadRequest
from tests.conftest import TEST_CAMERA_EXISTS, TEST_CHIME_EXISTS

try:
    from pydantic.v1 import ValidationError
except ImportError:
    from pydantic import ValidationError

if TYPE_CHECKING:
    from pyunifiprotect.data import Camera, Chime


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.parametrize("level", [-1, 0, 100, 200])
@pytest.mark.asyncio()
async def test_chime_set_volume(
    chime_obj: Optional[Chime],
    camera_obj: Optional[Camera],
    level: int,
):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")

    chime_obj.api.api_request.reset_mock()
    chime_obj.volume = 20
    chime_obj.ring_settings = [
        RingSetting(
            camera_id=camera_obj.id,
            repeat_times=1,  # type: ignore[arg-type]
            track_no=1,
            volume=20,
        ),
    ]

    if level in {-1, 200}:
        with pytest.raises(ValidationError):
            await chime_obj.set_volume(level)

        assert not chime_obj.api.api_request.called
    else:
        await chime_obj.set_volume(level)

        chime_obj.api.api_request.assert_called_with(
            f"chimes/{chime_obj.id}",
            method="patch",
            json={
                "volume": level,
                "ringSettings": [
                    {
                        "camera": camera_obj.id,
                        "repeatTimes": 1,
                        "trackNo": 1,
                        "volume": level,
                    },
                ],
            },
        )


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_set_volume_with_existing_custom(
    chime_obj: Optional[Chime],
    camera_obj: Optional[Camera],
):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.camera_ids = [camera_obj.id]
    chime_obj.volume = 100
    chime_obj.ring_settings = [
        RingSetting(
            camera_id=camera_obj.id,
            repeat_times=1,  # type: ignore[arg-type]
            track_no=1,
            volume=20,
        ),
    ]

    camera_obj.api.api_request.reset_mock()

    await chime_obj.set_volume(50)

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}",
        method="patch",
        json={"volume": 50},
    )


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_set_volume_for_camera(
    chime_obj: Optional[Chime],
    camera_obj: Optional[Camera],
):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.camera_ids = [camera_obj.id]
    chime_obj.volume = 100
    chime_obj.ring_settings = [
        RingSetting(
            camera_id=camera_obj.id,
            repeat_times=1,  # type: ignore[arg-type]
            track_no=1,
            volume=100,
        ),
    ]

    camera_obj.api.api_request.reset_mock()

    await chime_obj.set_volume_for_camera(camera_obj, 50)

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}",
        method="patch",
        json={
            "ringSettings": [
                {
                    "camera": camera_obj.id,
                    "repeatTimes": 1,
                    "trackNo": 1,
                    "volume": 50,
                },
            ],
        },
    )


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_set_volume_for_camera_not_exist(
    chime_obj: Optional[Chime],
    camera_obj: Optional[Camera],
):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.camera_ids = [camera_obj.id]
    chime_obj.volume = 100
    chime_obj.ring_settings = [
        RingSetting(
            camera_id="other-id",
            repeat_times=1,  # type: ignore[arg-type]
            track_no=1,
            volume=100,
        ),
    ]

    camera_obj.api.api_request.reset_mock()

    with pytest.raises(BadRequest):
        await chime_obj.set_volume_for_camera(camera_obj, 2)

    assert not chime_obj.api.api_request.called


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_chime_play(chime_obj: Optional[Chime]):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")

    await chime_obj.play()

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}/play-speaker",
        method="post",
        json=None,
    )


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_chime_play_with_options(chime_obj: Optional[Chime]):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")

    chime_obj.volume = 100
    chime_obj.repeat_times = 1
    chime_obj.track_no = 1
    chime_obj.api.api_request.reset_mock()

    await chime_obj.play(volume=50)

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}/play-speaker",
        method="post",
        json={
            "volume": 50,
            "repeatTimes": 1,
            "trackNo": 1,
        },
    )


@pytest.mark.skipif(not TEST_CHIME_EXISTS, reason="Missing testdata")
@pytest.mark.asyncio()
async def test_chime_play_buzzer(chime_obj: Optional[Chime]):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")

    await chime_obj.play_buzzer()

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}/play-buzzer",
        method="post",
    )


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_add_camera(
    chime_obj: Optional[Chime],
    camera_obj: Optional[Camera],
):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.api.api_request.reset_mock()
    chime_obj.camera_ids = []

    camera_obj.api.api_request.reset_mock()
    camera_obj.feature_flags.is_doorbell = True

    await chime_obj.add_camera(camera_obj)

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}",
        method="patch",
        json={"cameraIds": [camera_obj.id]},
    )


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_add_camera_not_doorbell(
    chime_obj: Optional[Chime],
    camera_obj: Optional[Camera],
):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.api.api_request.reset_mock()
    chime_obj.camera_ids = []

    camera_obj.api.api_request.reset_mock()
    camera_obj.feature_flags.is_doorbell = False

    with pytest.raises(BadRequest):
        await chime_obj.add_camera(camera_obj)

    assert not chime_obj.api.api_request.called


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_add_camera_exists(
    chime_obj: Optional[Chime],
    camera_obj: Optional[Camera],
):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.api.api_request.reset_mock()
    chime_obj.camera_ids = [camera_obj.id]

    camera_obj.api.api_request.reset_mock()
    camera_obj.feature_flags.is_doorbell = True

    with pytest.raises(BadRequest):
        await chime_obj.add_camera(camera_obj)

    assert not chime_obj.api.api_request.called


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_remove_camera(
    chime_obj: Optional[Chime],
    camera_obj: Optional[Camera],
):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.api.api_request.reset_mock()
    chime_obj.camera_ids = [camera_obj.id]

    camera_obj.api.api_request.reset_mock()
    camera_obj.feature_flags.is_doorbell = True

    await chime_obj.remove_camera(camera_obj)

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}",
        method="patch",
        json={"cameraIds": []},
    )


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_remove_camera_not_exists(
    chime_obj: Optional[Chime],
    camera_obj: Optional[Camera],
):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.api.api_request.reset_mock()
    chime_obj.camera_ids = []

    camera_obj.api.api_request.reset_mock()
    camera_obj.feature_flags.is_doorbell = True

    with pytest.raises(BadRequest):
        await chime_obj.remove_camera(camera_obj)

    assert not chime_obj.api.api_request.called


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_set_repeat_times(
    chime_obj: Optional[Chime],
    camera_obj: Optional[Camera],
):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.camera_ids = [camera_obj.id]
    chime_obj.repeat_times = 1
    chime_obj.ring_settings = [
        RingSetting(
            camera_id=camera_obj.id,
            repeat_times=1,  # type: ignore[arg-type]
            track_no=1,
            volume=100,
        ),
    ]

    camera_obj.api.api_request.reset_mock()

    await chime_obj.set_repeat_times(2)

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}",
        method="patch",
        json={
            "repeatTimes": 2,
            "ringSettings": [
                {
                    "camera": camera_obj.id,
                    "repeatTimes": 2,
                    "trackNo": 1,
                    "volume": 100,
                },
            ],
        },
    )


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_set_repeat_times_with_existing_custom(
    chime_obj: Optional[Chime],
    camera_obj: Optional[Camera],
):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.camera_ids = [camera_obj.id]
    chime_obj.repeat_times = 1
    chime_obj.ring_settings = [
        RingSetting(
            camera_id=camera_obj.id,
            repeat_times=3,  # type: ignore[arg-type]
            track_no=1,
            volume=100,
        ),
    ]

    camera_obj.api.api_request.reset_mock()

    await chime_obj.set_repeat_times(2)

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}",
        method="patch",
        json={"repeatTimes": 2},
    )


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_set_repeat_times_for_camera(
    chime_obj: Optional[Chime],
    camera_obj: Optional[Camera],
):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.camera_ids = [camera_obj.id]
    chime_obj.repeat_times = 1
    chime_obj.ring_settings = [
        RingSetting(
            camera_id=camera_obj.id,
            repeat_times=1,  # type: ignore[arg-type]
            track_no=1,
            volume=100,
        ),
    ]

    camera_obj.api.api_request.reset_mock()

    await chime_obj.set_repeat_times_for_camera(camera_obj, 2)

    chime_obj.api.api_request.assert_called_with(
        f"chimes/{chime_obj.id}",
        method="patch",
        json={
            "ringSettings": [
                {
                    "camera": camera_obj.id,
                    "repeatTimes": 2,
                    "trackNo": 1,
                    "volume": 100,
                },
            ],
        },
    )


@pytest.mark.skipif(
    not TEST_CHIME_EXISTS or not TEST_CAMERA_EXISTS,
    reason="Missing testdata",
)
@pytest.mark.asyncio()
async def test_chime_set_repeat_times_for_camera_not_exist(
    chime_obj: Optional[Chime],
    camera_obj: Optional[Camera],
):
    if chime_obj is None:
        pytest.skip("No chime_obj obj found")
    if camera_obj is None:
        pytest.skip("No camera_obj obj found")

    chime_obj.camera_ids = [camera_obj.id]
    chime_obj.repeat_times = 1
    chime_obj.ring_settings = [
        RingSetting(
            camera_id="other-id",
            repeat_times=1,  # type: ignore[arg-type]
            track_no=1,
            volume=100,
        ),
    ]

    camera_obj.api.api_request.reset_mock()

    with pytest.raises(BadRequest):
        await chime_obj.set_repeat_times_for_camera(camera_obj, 2)

    assert not chime_obj.api.api_request.called
