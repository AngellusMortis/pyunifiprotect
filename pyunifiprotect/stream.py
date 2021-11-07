from __future__ import annotations

from asyncio.subprocess import PIPE, Process, create_subprocess_exec
from pathlib import Path
from shlex import split
from typing import TYPE_CHECKING, List, Optional

from aioshutil import which

from pyunifiprotect.exceptions import BadRequest, StreamError

if TYPE_CHECKING:
    from pyunifiprotect.data import Camera


class FfmpegCommand:
    ffmpeg_path: Optional[Path]
    args: List[str]
    process: Optional[Process] = None

    _stdout: Optional[List[str]] = None
    _stderr: Optional[List[str]] = None

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

    async def get_output(self) -> List[str]:
        if self._stdout is not None:
            return self._stdout

        if not self.is_error or self.process is None:
            return []

        if self.process.stdout is None:
            stdout = b""
        else:
            stdout = await self.process.stdout.read()
        self._stdout = stdout.decode("utf8").split("\n")

        return self._stdout

    async def get_errors(self) -> List[str]:
        if self._stderr is not None:
            return self._stderr

        if not self.is_error or self.process is None:
            return []

        if self.process.stderr is None:
            stderr = b""
        else:
            stderr = await self.process.stderr.read()
        self._stderr = stderr.decode("utf8").split("\n")

        return self._stderr

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

        self.process = await create_subprocess_exec(self.ffmpeg_path, *self.args, stdout=PIPE, stderr=PIPE)

    async def stop(self) -> None:
        if self.process is None:
            raise StreamError("ffmpeg has not started")

        self.process.kill()
        await self.process.wait()

    async def run_until_complete(self) -> None:
        if self.is_started:
            raise StreamError("ffmpeg command already started")

        await self.start()
        if self.process is None:
            raise StreamError("Could not start stream")

        await self.process.wait()


class TalkbackStream(FfmpegCommand):
    camera: Camera
    content_url: str

    def __init__(self, camera: Camera, content_url: str, ffmpeg_path: Optional[Path] = None):
        if not camera.feature_flags.has_speaker:
            raise BadRequest("Camera does not have a speaker for talkback")

        input_args = self.get_args_from_url(content_url)
        if len(input_args) > 0:
            input_args += " "

        cmd = f"-loglevel error -hide_banner {input_args}-i {content_url} -vn -acodec {camera.talkback_settings.type_fmt} -ac {camera.talkback_settings.channels} -ar {camera.talkback_settings.sampling_rate} -bits_per_raw_sample {camera.talkback_settings.bits_per_sample} -map 0:a -aq {camera.talkback_settings.quality} -f adts udp://{camera.host}:{camera.talkback_settings.bind_port}"

        super().__init__(cmd, ffmpeg_path)

    @classmethod
    def get_args_from_url(cls, content_url: str) -> str:
        # TODO:
        return ""
