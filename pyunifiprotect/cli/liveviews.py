from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import typer

from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.cli import base
from pyunifiprotect.data import Liveview

app = typer.Typer(rich_markup_mode="rich")

ARG_DEVICE_ID = typer.Argument(None, help="ID of liveview to select for subcommands")
ALL_COMMANDS = {"list-ids": app.command(name="list-ids")(base.list_ids)}

app.command(name="protect-url")(base.protect_url)


@dataclass
class LiveviewContext(base.CliContext):
    devices: dict[str, Liveview]
    device: Liveview | None = None


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: Optional[str] = ARG_DEVICE_ID) -> None:
    """
    Liveviews CLI.

    Returns full list of Liveviews without any arguments passed.
    """

    protect: ProtectApiClient = ctx.obj.protect
    context = LiveviewContext(
        protect=ctx.obj.protect, device=None, devices=protect.bootstrap.liveviews, output_format=ctx.obj.output_format
    )
    ctx.obj = context

    if device_id is not None and device_id not in ALL_COMMANDS:
        if (device := protect.bootstrap.liveviews.get(device_id)) is None:
            typer.secho("Invalid liveview ID", fg="red")
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
def owner(ctx: typer.Context) -> None:
    """Gets the owner for the liveview."""

    base.require_device_id(ctx)
    obj: Liveview = ctx.obj.device
    base.print_unifi_obj(obj.owner, ctx.obj.output_format)
