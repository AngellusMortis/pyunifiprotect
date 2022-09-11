from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import typer

from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.cli import base
from pyunifiprotect.data import Doorlock

app = typer.Typer(rich_markup_mode="rich")

ARG_DEVICE_ID = typer.Argument(None, help="ID of doorlock to select for subcommands")


@dataclass
class DoorlockContext(base.CliContext):
    devices: dict[str, Doorlock]
    device: Doorlock | None = None


ALL_COMMANDS, DEVICE_COMMANDS = base.init_common_commands(app)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: Optional[str] = ARG_DEVICE_ID) -> None:
    """
    Doorlock device CLI.

    Returns full list of Doorlocks without any arguments passed.
    """

    protect: ProtectApiClient = ctx.obj.protect
    context = DoorlockContext(
        protect=ctx.obj.protect, device=None, devices=protect.bootstrap.doorlocks, output_format=ctx.obj.output_format
    )
    ctx.obj = context

    if device_id is not None and device_id not in ALL_COMMANDS:
        if (device := protect.bootstrap.doorlocks.get(device_id)) is None:
            typer.secho("Invalid doorlock ID", fg="red")
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
    """Returns or sets tha paired camera for a doorlock."""

    base.require_device_id(ctx)
    obj: Doorlock = ctx.obj.device

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
    """Sets status light for the lock."""

    base.require_device_id(ctx)
    obj: Doorlock = ctx.obj.device

    base.run(ctx, obj.set_status_light(enabled))


@app.command()
def set_auto_close_time(ctx: typer.Context, duration: int = typer.Argument(..., min=0, max=3600)) -> None:
    """Sets auto-close time for the lock (in seconds). 0 = disabled."""

    base.require_device_id(ctx)
    obj: Doorlock = ctx.obj.device

    base.run(ctx, obj.set_auto_close_time(timedelta(seconds=duration)))


@app.command()
def unlock(ctx: typer.Context) -> None:
    """Unlocks the lock."""

    base.require_device_id(ctx)
    obj: Doorlock = ctx.obj.device
    base.run(ctx, obj.open_lock())


@app.command()
def lock(ctx: typer.Context) -> None:
    """Locks the lock."""

    base.require_device_id(ctx)
    obj: Doorlock = ctx.obj.device
    base.run(ctx, obj.close_lock())


@app.command()
def calibrate(ctx: typer.Context, force: bool = base.OPTION_FORCE) -> None:
    """
    Calibrate the doorlock.

    Door must be open and lock unlocked.
    """

    base.require_device_id(ctx)
    obj: Doorlock = ctx.obj.device

    if force or typer.confirm("Is the door open and unlocked?"):
        base.run(ctx, obj.calibrate())
