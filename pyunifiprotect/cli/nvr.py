import asyncio
from dataclasses import dataclass
from datetime import timedelta
import json
from typing import Any, Coroutine

import typer

from pyunifiprotect.cli.base import CliContext
from pyunifiprotect.data import NVR, ProtectBaseObject

app = typer.Typer()

ARG_TIMEOUT = typer.Argument(..., help="Timeout (in seconds)")
ARG_DOORBELL_MESSAGE = typer.Argument(..., help="ASCII only. Max length 30")


@dataclass
class NVRContext(CliContext):
    nvr: NVR


def _run(ctx: typer.Context, func: Coroutine[Any, Any, None]) -> None:
    async def callback() -> None:
        await func
        await ctx.obj.protect.close_session()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(callback())


def _print_unifi_obj(obj: ProtectBaseObject) -> None:
    typer.echo(json.dumps(obj.unifi_dict(), indent=2))


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """UniFi Protect NVR CLI"""

    context = NVRContext(protect=ctx.obj.protect, nvr=ctx.obj.protect.bootstrap.nvr)
    ctx.obj = context

    if not ctx.invoked_subcommand:
        _print_unifi_obj(context.nvr)


@app.command()
def protect_url(ctx: typer.Context) -> None:
    """Gets UniFi Protect management URL."""

    nvr: NVR = ctx.obj.nvr
    typer.echo(nvr.protect_url)


@app.command()
def set_default_reset_timeout(ctx: typer.Context, timeout: int = ARG_TIMEOUT) -> None:
    """
    Sets default message reset timeout.

    This is how long until a custom message is reset back to the default message if no
    timeout is passed in when the custom message is set.
    """

    nvr: NVR = ctx.obj.nvr
    _run(ctx, nvr.set_default_reset_timeout(timedelta(seconds=timeout)))
    _print_unifi_obj(nvr.doorbell_settings)


@app.command()
def set_default_doorbell_message(ctx: typer.Context, msg: str = ARG_DOORBELL_MESSAGE) -> None:
    """
    Sets default message for doorbell.

    This is the message that is set when a custom doorbell message times out or an empty
    one is set.
    """

    nvr: NVR = ctx.obj.nvr
    _run(ctx, nvr.set_default_doorbell_message(msg))
    _print_unifi_obj(nvr.doorbell_settings)


@app.command()
def add_custom_doorbell_message(ctx: typer.Context, msg: str = ARG_DOORBELL_MESSAGE) -> None:
    """Adds a custom doorbell message."""

    nvr: NVR = ctx.obj.nvr
    _run(ctx, nvr.add_custom_doorbell_message(msg))
    _print_unifi_obj(nvr.doorbell_settings)


@app.command()
def remove_custom_doorbell_message(ctx: typer.Context, msg: str = ARG_DOORBELL_MESSAGE) -> None:
    """Removes a custom doorbell message."""

    nvr: NVR = ctx.obj.nvr
    _run(ctx, nvr.remove_custom_doorbell_message(msg))
    _print_unifi_obj(nvr.doorbell_settings)
