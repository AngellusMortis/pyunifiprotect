from __future__ import annotations

import asyncio
from asyncio.streams import StreamReader
from asyncio.subprocess import PIPE, Process, create_subprocess_exec
import logging
from pathlib import Path
from shlex import split
from typing import TYPE_CHECKING, List, Optional
from urllib.parse import urlparse

from aioshutil import which

from pyunifiprotect.exceptions import BadRequest, StreamError

if TYPE_CHECKING:
    from pyunifiprotect.data import Camera

_LOGGER = logging.getLogger(__name__)


class FfmpegCommand:
    ffmpeg_path: Optional[Path]
    args: List[str]
    process: Optional[Process] = None

    stdout: List[str] = []
    stderr: List[str] = []

    def __init__(self, cmd: str, ffmpeg_path: Optional[Path] = None) -> None:
        self.args = split(cmd)

        if "ffmpeg" in self.args[0] and ffmpeg_path is None:
            self.ffmpeg_path = Path(self.args.pop(0))
        else:
            self.ffmpeg_path = ffmpeg_path

    @property
    def is_started(self) -> bool:
        return self.process is not None

    @property
    def is_running(self) -> bool:
        if self.process is None:
            return False

        return self.process.returncode is None

    @property
    def is_error(self) -> bool:
        if self.process is None:
            raise StreamError("ffmpeg has not started")

        if self.is_running:
            return False

        return self.process.returncode != 0

    async def start(self) -> None:
        if self.is_started:
            raise StreamError("ffmpeg command already started")

        if self.ffmpeg_path is None:
            system_ffmpeg = await which("ffmpeg")

            if system_ffmpeg is None:
                raise StreamError("Could not find ffmpeg")
            self.ffmpeg_path = Path(system_ffmpeg)

        if not self.ffmpeg_path.exists():
            raise StreamError("Could not find ffmpeg")

        _LOGGER.debug("ffmpeg: %s %s", self.ffmpeg_path, " ".join(self.args))
        self.process = await create_subprocess_exec(self.ffmpeg_path, *self.args, stdout=PIPE, stderr=PIPE)

    async def stop(self) -> None:
        if self.process is None:
            raise StreamError("ffmpeg has not started")

        self.process.kill()
        await self.process.wait()

    async def _read_stream(self, stream: Optional[StreamReader], attr: str) -> None:
        if stream is None:
            return

        while True:
            line = await stream.readline()
            if line:
                getattr(self, attr).append(line.decode("utf8").rstrip())
            else:
                break

    async def run_until_complete(self) -> None:
        if not self.is_started:
            await self.start()

        if self.process is None:
            raise StreamError("Could not start stream")

        await asyncio.wait(
            [self._read_stream(self.process.stdout, "stdout"), self._read_stream(self.process.stderr, "stderr")]
        )
        await self.process.wait()


class TalkbackStream(FfmpegCommand):
    camera: Camera
    content_url: str

    def __init__(self, camera: Camera, content_url: str, ffmpeg_path: Optional[Path] = None):
        if not camera.feature_flags.has_speaker:
            raise BadRequest("Camera does not have a speaker for talkback")

        content_url = self.clean_url(content_url)
        input_args = self.get_args_from_url(content_url)
        if len(input_args) > 0:
            input_args += " "

        bitrate = camera.talkback_settings.bits_per_sample * 1000
        # 8000 seems to result in best quality without overloading the camera
        udp_bitrate = bitrate + 8000

        # vn = no video
        # acodec = audio codec to encode output in (aac)
        # ac = number of output channels (1)
        # ar = output sampling rate (22050)
        # b:a = set bit rate of output audio
        cmd = (
            "-loglevel info -hide_banner "
            f'{input_args}-i "{content_url}" -vn '
            f"-acodec {camera.talkback_settings.type_fmt} -ac {camera.talkback_settings.channels} "
            f"-ar {camera.talkback_settings.sampling_rate} -b:a {bitrate} -map 0:a "
            f'-f adts "udp://{camera.host}:{camera.talkback_settings.bind_port}?bitrate={udp_bitrate}"'
        )

        super().__init__(cmd, ffmpeg_path)

    @classmethod
    def clean_url(cls, content_url: str) -> str:
        parsed = urlparse(content_url)
        if parsed.scheme in ["file", ""]:
            path = Path(parsed.netloc + parsed.path)
            if not path.exists():
                raise BadRequest(f"File {path} does not exist")
            content_url = str(path.absolute())

        return content_url

    @classmethod
    def get_args_from_url(cls, content_url: str) -> str:
        # TODO:
        return ""
