from dataclasses import dataclass
from typing import Optional

import typer

from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.cli import base
from pyunifiprotect.data import Light

app = typer.Typer()

ARG_DEVICE_ID = typer.Argument(None, help="ID of light to select for subcommands")


@dataclass
class LightContext(base.CliContext):
    devices: dict[str, Light]
    device: Light | None = None


ALL_COMMANDS, DEVICE_COMMANDS = base.init_common_commands(app)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: Optional[str] = ARG_DEVICE_ID) -> None:
    """
    UniFi Protect Light CLI.

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
            base.print_unifi_obj(ctx.obj.device)
            return

        base.print_unifi_dict(ctx.obj.devices)
