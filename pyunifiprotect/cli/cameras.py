from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, cast

import typer

from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.cli import base
from pyunifiprotect.data import Camera, ChimeType

app = typer.Typer()

ARG_DEVICE_ID = typer.Argument(None, help="ID of camera to select for subcommands")


@dataclass
class CameraContext(base.CliContext):
    devices: dict[str, Camera]
    device: Camera | None = None


ALL_COMMANDS, DEVICE_COMMANDS = base.init_common_commands(app)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: Optional[str] = ARG_DEVICE_ID) -> None:
    """
    UniFi Protect Camera CLI.

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
    obj: Camera = ctx.obj.device
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
    obj: Camera = ctx.obj.device
    if enabled is None:
        base.json_output(obj.is_privacy_on)
        return
    base.run(ctx, obj.set_privacy(enabled))


@app.command()
def chime_type(ctx: typer.Context, value: Optional[ChimeType] = None) -> None:
    """Returns/sets the current chime type if the camera has a chime."""

    base.require_device_id(ctx)
    obj: Camera = ctx.obj.device
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
    obj: Camera = ctx.obj.device
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
    package: bool = typer.Option(False, "-p", "--package", help="Get package camera"),
) -> None:
    """Takes snapshot of camera."""

    base.require_device_id(ctx)
    obj: Camera = ctx.obj.device

    if package:
        if not obj.feature_flags.has_package_camera:
            typer.secho("Camera does not have package camera", fg="red")
            raise typer.Exit(1)

        snapshot = base.run(ctx, obj.get_package_snapshot(width, height))
    else:
        snapshot = base.run(ctx, obj.get_snapshot(width, height))

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
) -> None:
    """Exports video of camera.

    Exports are approximate. It will not export with down to the second
    accuracy so it may be +/- a few seconds.

    Uses your locale timezone. If it is not configured correctly,
    it will default to UTC. You can override your timezone with the
    TZ environment variable.
    """

    base.require_device_id(ctx)
    obj: Camera = ctx.obj.device

    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    start = start.replace(tzinfo=local_tz)
    end = end.replace(tzinfo=local_tz)

    if channel == 4 and not obj.feature_flags.has_package_camera:
        typer.secho("Camera does not have package camera", fg="red")
        raise typer.Exit(1)

    video = base.run(ctx, obj.get_video(start, end, channel))

    if video is None:
        typer.secho("Could not get snapshot", fg="red")
        raise typer.Exit(1)

    with open(output_path, "wb") as f:
        f.write(video)
