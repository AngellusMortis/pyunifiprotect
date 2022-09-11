from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, cast

from rich.progress import Progress
import typer

from pyunifiprotect import data as d
from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.cli import base

app = typer.Typer(rich_markup_mode="rich")

ARG_DEVICE_ID = typer.Argument(None, help="ID of camera to select for subcommands")


@dataclass
class CameraContext(base.CliContext):
    devices: dict[str, d.Camera]
    device: d.Camera | None = None


ALL_COMMANDS, DEVICE_COMMANDS = base.init_common_commands(app)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: Optional[str] = ARG_DEVICE_ID) -> None:
    """
    Camera device CLI.

    Returns full list of Cameras without any arguments passed.
    """

    protect: ProtectApiClient = ctx.obj.protect
    context = CameraContext(
        protect=ctx.obj.protect, device=None, devices=protect.bootstrap.cameras, output_format=ctx.obj.output_format
    )
    ctx.obj = context

    if device_id is not None and device_id not in ALL_COMMANDS:
        if (device := protect.bootstrap.cameras.get(device_id)) is None:
            typer.secho("Invalid camera ID", fg="red")
            raise typer.Exit(1)
        ctx.obj.device = device

    if not ctx.invoked_subcommand:
        if device_id in ALL_COMMANDS:
            ctx.invoke(ALL_COMMANDS[device_id], ctx)
            return

        if ctx.obj.device is not None:
            base.print_unifi_obj(ctx.obj.device, ctx.obj.output_format)
            return

        base.print_unifi_dict(ctx.obj.devices)


@app.command()
def timelapse_url(ctx: typer.Context) -> None:
    """Returns UniFi Protect timelapse URL."""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device
    if ctx.obj.output_format == base.OutputFormatEnum.JSON:
        base.json_output(obj.timelapse_url)
    else:
        typer.echo(obj.timelapse_url)


@app.command()
def privacy_mode(ctx: typer.Context, enabled: Optional[bool] = typer.Argument(None)) -> None:
    """Returns/sets library managed privacy mode.

    Does not change the microphone sensitivity or recording mode.
    It must be changed seperately.
    """

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device
    if enabled is None:
        base.json_output(obj.is_privacy_on)
        return
    base.run(ctx, obj.set_privacy(enabled))


@app.command()
def chime_type(ctx: typer.Context, value: Optional[d.ChimeType] = None) -> None:
    """Returns/sets the current chime type if the camera has a chime."""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device
    if not obj.feature_flags.has_chime:
        typer.secho("Camera does not have a chime", fg="red")
        raise typer.Exit(1)

    if value is None:
        if ctx.obj.output_format == base.OutputFormatEnum.JSON:
            base.json_output(obj.chime_type)
        elif obj.chime_type is not None:
            typer.echo(obj.chime_type.name)
        return

    base.run(ctx, obj.set_chime_type(value))


@app.command()
def stream_urls(ctx: typer.Context) -> None:
    """Returns all of the enabled RTSP(S) URLs."""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device
    data: list[tuple[str, str]] = []
    for channel in obj.channels:
        if channel.is_rtsp_enabled:
            rtsp_url = cast(str, channel.rtsp_url)
            rtsps_url = cast(str, channel.rtsps_url)
            data.append((f"{channel.name} RTSP", rtsp_url))
            data.append((f"{channel.name} RTSPS", rtsps_url))

    if ctx.obj.output_format == base.OutputFormatEnum.JSON:
        base.json_output(data)
    else:
        for name, url in data:
            typer.echo(f"{name:20}\t{url}")


@app.command()
def save_snapshot(
    ctx: typer.Context,
    output_path: Path = typer.Argument(..., help="JPEG format"),
    width: Optional[int] = typer.Option(None, "-w", "--width"),
    height: Optional[int] = typer.Option(None, "-h", "--height"),
    dt: Optional[datetime] = typer.Option(None, "-t", "--timestamp"),
    package: bool = typer.Option(False, "-p", "--package", help="Get package camera"),
) -> None:
    """
    Takes snapshot of camera.

    If you specify a timestamp, they are approximate. It will not export with down to the second
    accuracy so it may be +/- a few seconds.

    Timestamps use your locale timezone. If it is not configured correctly,
    it will default to UTC. You can override your timezone with the
    TZ environment variable.
    """

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    if dt is not None:
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        dt = dt.replace(tzinfo=local_tz)

    if package:
        if not obj.feature_flags.has_package_camera:
            typer.secho("Camera does not have package camera", fg="red")
            raise typer.Exit(1)
        snapshot = base.run(ctx, obj.get_package_snapshot(width, height, dt=dt))
    else:
        snapshot = base.run(ctx, obj.get_snapshot(width, height, dt=dt))

    if snapshot is None:
        typer.secho("Could not get snapshot", fg="red")
        raise typer.Exit(1)

    with open(output_path, "wb") as f:
        f.write(snapshot)


@app.command()
def save_video(
    ctx: typer.Context,
    output_path: Path = typer.Argument(..., help="MP4 format"),
    start: datetime = typer.Argument(...),
    end: datetime = typer.Argument(...),
    channel: int = typer.Option(0, "-c", "--channel", min=0, max=3, help="0 = High, 1 = Medium, 2 = Low, 3 = Package"),
    fps: Optional[int] = typer.Option(
        None, "--fps", min=1, max=40, help="Export as timelapse. 4 = 60x, 8 = 120x, 20 = 300x, 40 = 600x"
    ),
) -> None:
    """Exports video of camera.

    Exports are approximate. It will not export with down to the second
    accuracy so it may be +/- a few seconds.

    Uses your locale timezone. If it is not configured correctly,
    it will default to UTC. You can override your timezone with the
    TZ environment variable.
    """

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    start = start.replace(tzinfo=local_tz)
    end = end.replace(tzinfo=local_tz)

    if channel == 4 and not obj.feature_flags.has_package_camera:
        typer.secho("Camera does not have package camera", fg="red")
        raise typer.Exit(1)

    with Progress() as pb:
        task_id = pb.add_task("(1/2) Exporting", total=100)

        async def callback(step: int, current: int, total: int) -> None:
            pb.update(task_id, total=total, completed=current, description="(2/2) Downloading")

        base.run(
            ctx,
            obj.get_video(start, end, channel, output_file=output_path, progress_callback=callback, fps=fps),
        )


@app.command()
def play_audio(
    ctx: typer.Context,
    url: str = typer.Argument(..., help="ffmpeg playable URL"),
    ffmpeg_path: Optional[Path] = typer.Option(
        None, "--ffmpeg-path", help="Path to ffmpeg executable", envvar="FFMPEG_PATH"
    ),
) -> None:
    """Plays audio file on camera speaker."""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device
    base.run(ctx, obj.play_audio(url, ffmpeg_path=ffmpeg_path))


@app.command()
def smart_detects(
    ctx: typer.Context,
    values: list[d.SmartDetectObjectType] = typer.Argument(None, help="Set to [] to empty list of detect types."),
    add: bool = typer.Option(False, "-a", "--add", help="Add values instead of set"),
    remove: bool = typer.Option(False, "-r", "--remove", help="Remove values instead of set"),
) -> None:
    """Returns/set smart detect types for camera."""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    if add and remove:
        typer.secho("Add and remove are mutally exclusive", fg="red")
        raise typer.Exit(1)

    if not obj.feature_flags.has_smart_detect:
        typer.secho("Camera does not support smart detections", fg="red")
        raise typer.Exit(1)

    if len(values) == 0:
        if ctx.obj.output_format == base.OutputFormatEnum.JSON:
            base.json_output(obj.smart_detect_settings.object_types)
        else:
            for value in obj.smart_detect_settings.object_types:
                typer.echo(value.value)
        return

    if len(values) == 1 and values[0] == "[]":
        values = []

    for value in values:
        if value not in obj.feature_flags.smart_detect_types:
            typer.secho(f"Camera does not support {value}", fg="red")
            raise typer.Exit(1)

    if add:
        values = list(set(obj.smart_detect_settings.object_types) | set(values))
    elif remove:
        values = list(set(obj.smart_detect_settings.object_types) - set(values))

    obj.smart_detect_settings.object_types = values
    base.run(ctx, obj.save_device())


@app.command()
def set_motion_detection(ctx: typer.Context, enabled: bool) -> None:
    """Sets motion detection on camera"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_motion_detection(enabled))


@app.command()
def set_recording_mode(ctx: typer.Context, mode: d.RecordingMode) -> None:
    """Sets recording mode on camera"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_recording_mode(mode))


@app.command()
def set_ir_led_mode(ctx: typer.Context, mode: d.IRLEDMode) -> None:
    """Sets IR LED mode on camera"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_ir_led_model(mode))


@app.command()
def set_status_light(ctx: typer.Context, enabled: bool) -> None:
    """Sets status indicicator light on camera"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_status_light(enabled))


@app.command()
def set_hdr(ctx: typer.Context, enabled: bool) -> None:
    """Sets HDR (High Dynamic Range) on camera"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_hdr(enabled))


@app.command()
def set_video_mode(ctx: typer.Context, mode: d.VideoMode) -> None:
    """Sets video mode on camera"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_video_mode(mode))


@app.command()
def set_camera_zoom(ctx: typer.Context, level: int = typer.Argument(..., min=0, max=100)) -> None:
    """Sets zoom level for camera"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_camera_zoom(level))


@app.command()
def set_wdr_level(ctx: typer.Context, level: int = typer.Argument(..., min=0, max=3)) -> None:
    """Sets WDR (Wide Dynamic Range) on camera"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_wdr_level(level))


@app.command()
def set_mic_volume(ctx: typer.Context, level: int = typer.Argument(..., min=0, max=100)) -> None:
    """Sets the mic sensitivity level on camera"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_mic_volume(level))


@app.command()
def set_speaker_volume(ctx: typer.Context, level: int = typer.Argument(..., min=0, max=100)) -> None:
    """Sets the speaker sensitivity level on camera"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_speaker_volume(level))


@app.command()
def set_system_sounds(ctx: typer.Context, enabled: bool) -> None:
    """Sets system sound playback through speakers"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_system_sounds(enabled))


@app.command()
def set_osd_name(ctx: typer.Context, enabled: bool) -> None:
    """Sets whether camera name is in the On Screen Display"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_osd_name(enabled))


@app.command()
def set_osd_date(ctx: typer.Context, enabled: bool) -> None:
    """Sets whether current date is in the On Screen Display"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_osd_date(enabled))


@app.command()
def set_osd_logo(ctx: typer.Context, enabled: bool) -> None:
    """Sets whether the UniFi logo is in the On Screen Display"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_osd_logo(enabled))


@app.command()
def set_osd_bitrate(ctx: typer.Context, enabled: bool) -> None:
    """Sets whether camera bitrate is in the On Screen Display"""

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_osd_bitrate(enabled))


@app.command()
def set_lcd_text(
    ctx: typer.Context,
    text_type: Optional[d.DoorbellMessageType] = typer.Argument(
        None, help="No value sets it back to the global default doorbell message."
    ),
    text: Optional[str] = typer.Argument(None, help="Only for CUSTOM_MESSAGE text type"),
    reset_at: Optional[datetime] = typer.Option(None, "-r", "--reset-time", help="Does not apply to default message"),
) -> None:
    """Sets doorbell LCD text.

    Uses your locale timezone. If it is not configured correctly,
    it will default to UTC. You can override your timezone with the
    TZ environment variable.
    """

    if reset_at is not None:
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        reset_at = reset_at.replace(tzinfo=local_tz)

    base.require_device_id(ctx)
    obj: d.Camera = ctx.obj.device

    base.run(ctx, obj.set_lcd_text(text_type, text, reset_at))
