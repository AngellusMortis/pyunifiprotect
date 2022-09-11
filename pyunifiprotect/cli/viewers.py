from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import typer

from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.cli import base
from pyunifiprotect.data import Viewer

app = typer.Typer(rich_markup_mode="rich")

ARG_DEVICE_ID = typer.Argument(None, help="ID of viewer to select for subcommands")


@dataclass
class ViewerContext(base.CliContext):
    devices: dict[str, Viewer]
    device: Viewer | None = None


ALL_COMMANDS, DEVICE_COMMANDS = base.init_common_commands(app)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: Optional[str] = ARG_DEVICE_ID) -> None:
    """
    Viewers device CLI.

    Returns full list of Viewers without any arguments passed.
    """

    protect: ProtectApiClient = ctx.obj.protect
    context = ViewerContext(
        protect=ctx.obj.protect, device=None, devices=protect.bootstrap.viewers, output_format=ctx.obj.output_format
    )
    ctx.obj = context

    if device_id is not None and device_id not in ALL_COMMANDS:
        if (device := protect.bootstrap.viewers.get(device_id)) is None:
            typer.secho("Invalid viewer ID", fg="red")
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
def liveview(ctx: typer.Context, liveview_id: Optional[str] = typer.Argument(None)) -> None:
    """Returns or sets the current liveview."""

    base.require_device_id(ctx)
    obj: Viewer = ctx.obj.device

    if liveview_id is None:
        base.print_unifi_obj(obj.liveview, ctx.obj.output_format)
    else:
        protect: ProtectApiClient = ctx.obj.protect
        if (liveview_obj := protect.bootstrap.liveviews.get(liveview_id)) is None:
            typer.secho("Invalid liveview ID")
            raise typer.Exit(1)
        base.run(ctx, obj.set_liveview(liveview_obj))
