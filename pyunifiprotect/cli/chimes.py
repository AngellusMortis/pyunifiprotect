from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import typer

from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.cli import base
from pyunifiprotect.data import Chime

app = typer.Typer(rich_markup_mode="rich")

ARG_DEVICE_ID = typer.Argument(None, help="ID of chime to select for subcommands")


@dataclass
class ChimeContext(base.CliContext):
    devices: dict[str, Chime]
    device: Chime | None = None


ALL_COMMANDS, DEVICE_COMMANDS = base.init_common_commands(app)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: Optional[str] = ARG_DEVICE_ID) -> None:
    """
    Chime device CLI.

    Returns full list of Chimes without any arguments passed.
    """

    protect: ProtectApiClient = ctx.obj.protect
    context = ChimeContext(
        protect=ctx.obj.protect, device=None, devices=protect.bootstrap.chimes, output_format=ctx.obj.output_format
    )
    ctx.obj = context

    if device_id is not None and device_id not in ALL_COMMANDS:
        if (device := protect.bootstrap.chimes.get(device_id)) is None:
            typer.secho("Invalid chime ID", fg="red")
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
def cameras(
    ctx: typer.Context,
    camera_ids: list[str] = typer.Argument(None, help="Set to [] to empty list of cameras"),
    add: bool = typer.Option(False, "-a", "--add", help="Add cameras instead of set"),
    remove: bool = typer.Option(False, "-r", "--remove", help="Remove cameras instead of set"),
) -> None:
    """Returns or sets paired doorbells for the chime."""

    base.require_device_id(ctx)
    obj: Chime = ctx.obj.device

    if add and remove:
        typer.secho("Add and remove are mutally exclusive", fg="red")
        raise typer.Exit(1)

    if len(camera_ids) == 0:
        base.print_unifi_list(obj.cameras)
        return

    protect: ProtectApiClient = ctx.obj.protect

    if len(camera_ids) == 1 and camera_ids[0] == "[]":
        camera_ids = []

    for camera_id in camera_ids:
        if (camera := protect.bootstrap.cameras.get(camera_id)) is None:
            typer.secho(f"Invalid camera ID: {camera_id}")
            raise typer.Exit(1)

        if not camera.feature_flags.has_chime:
            typer.secho(f"Camera is not a doorbell: {camera_id}")
            raise typer.Exit(1)

    if add:
        camera_ids = list(set(obj.camera_ids) | set(camera_ids))
    elif remove:
        camera_ids = list(set(obj.camera_ids) - set(camera_ids))

    obj.camera_ids = camera_ids
    base.run(ctx, obj.save_device())


@app.command()
def play(ctx: typer.Context) -> None:
    """Plays chime tone."""

    base.require_device_id(ctx)
    obj: Chime = ctx.obj.device
    base.run(ctx, obj.play())


@app.command()
def play_buzzer(ctx: typer.Context) -> None:
    """Plays chime buzzer."""

    base.require_device_id(ctx)
    obj: Chime = ctx.obj.device
    base.run(ctx, obj.play_buzzer())
