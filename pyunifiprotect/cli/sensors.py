from dataclasses import dataclass
from typing import Optional

import typer

from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.cli import base
from pyunifiprotect.data import Sensor

app = typer.Typer()

ARG_DEVICE_ID = typer.Argument(None, help="ID of sensor to select for subcommands")


@dataclass
class SensorContext(base.CliContext):
    devices: dict[str, Sensor]
    device: Sensor | None = None


ALL_COMMANDS, DEVICE_COMMANDS = base.init_common_commands(app)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, device_id: Optional[str] = ARG_DEVICE_ID) -> None:
    """
    UniFi Protect Sensor CLI.

    Returns full list of Sensors without any arguments passed.
    """

    protect: ProtectApiClient = ctx.obj.protect
    context = SensorContext(
        protect=ctx.obj.protect, device=None, devices=protect.bootstrap.sensors, output_format=ctx.obj.output_format
    )
    ctx.obj = context

    if device_id is not None and device_id not in ALL_COMMANDS:
        if (device := protect.bootstrap.sensors.get(device_id)) is None:
            typer.secho("Invalid sensor ID", fg="red")
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
