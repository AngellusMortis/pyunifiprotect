from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import typer

from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.cli import base
from pyunifiprotect.data import Light

app = typer.Typer(rich_markup_mode="rich")

ARG_DEVICE_ID = typer.Argument(None, help="ID of light to select for subcommands")


@dataclass
class LightContext(base.CliContext):
    devices: dict[str, Light]
    device: Light | None = None


ALL_COMMANDS, DEVICE_COMMANDS = base.init_common_commands(app)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: Optional[str] = ARG_DEVICE_ID) -> None:
    """
    Lights device CLI.

    Returns full list of Viewers without any arguments passed.
    """

    protect: ProtectApiClient = ctx.obj.protect
    context = LightContext(
        protect=ctx.obj.protect, device=None, devices=protect.bootstrap.lights, output_format=ctx.obj.output_format
    )
    ctx.obj = context

    if device_id is not None and device_id not in ALL_COMMANDS:
        if (device := protect.bootstrap.lights.get(device_id)) is None:
            typer.secho("Invalid light ID", fg="red")
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
def camera(ctx: typer.Context, camera_id: Optional[str] = typer.Argument(None)) -> None:
    """Returns or sets tha paired camera for a light."""

    base.require_device_id(ctx)
    obj: Light = ctx.obj.device

    if camera_id is None:
        base.print_unifi_obj(obj.camera, ctx.obj.output_format)
    else:
        protect: ProtectApiClient = ctx.obj.protect
        if (camera_obj := protect.bootstrap.cameras.get(camera_id)) is None:
            typer.secho("Invalid camera ID")
            raise typer.Exit(1)
        base.run(ctx, obj.set_paired_camera(camera_obj))


@app.command()
def set_status_light(ctx: typer.Context, enabled: bool) -> None:
    """Sets status light for light device."""

    base.require_device_id(ctx)
    obj: Light = ctx.obj.device

    base.run(ctx, obj.set_status_light(enabled))


@app.command()
def set_led_level(ctx: typer.Context, led_level: int = typer.Argument(..., min=1, max=6)) -> None:
    """Sets brightness of LED on light."""

    base.require_device_id(ctx)
    obj: Light = ctx.obj.device

    base.run(ctx, obj.set_led_level(led_level))


@app.command()
def set_sensitivity(ctx: typer.Context, sensitivity: int = typer.Argument(..., min=0, max=100)) -> None:
    """Sets motion sensitivity for the light."""

    base.require_device_id(ctx)
    obj: Light = ctx.obj.device

    base.run(ctx, obj.set_sensitivity(sensitivity))


@app.command()
def set_duration(ctx: typer.Context, duration: int = typer.Argument(..., min=15, max=900)) -> None:
    """Sets timeout duration (in seconds) for light."""

    base.require_device_id(ctx)
    obj: Light = ctx.obj.device

    base.run(ctx, obj.set_duration(timedelta(seconds=duration)))
