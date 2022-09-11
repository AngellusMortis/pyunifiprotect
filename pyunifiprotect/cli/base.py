from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Coroutine, Mapping, Optional, Sequence, TypeVar

import orjson
from pydantic import ValidationError
import typer

from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.data import NVR, ProtectAdoptableDeviceModel, ProtectBaseObject
from pyunifiprotect.exceptions import BadRequest, NvrError, StreamError

T = TypeVar("T")

OPTION_FORCE = typer.Option(False, "-f", "--force", help="Skip confirmation prompt")


class OutputFormatEnum(str, Enum):
    JSON = "json"
    PLAIN = "plain"


@dataclass
class CliContext:
    protect: ProtectApiClient
    output_format: OutputFormatEnum


def run(ctx: typer.Context, func: Coroutine[Any, Any, T]) -> T:
    """Helper method to call async function and clean up API client"""

    async def callback() -> T:
        return_value = await func
        await ctx.obj.protect.close_session()
        return return_value

    loop = asyncio.get_event_loop()
    try:
        return loop.run_until_complete(callback())
    except (BadRequest, ValidationError, StreamError, NvrError) as err:
        typer.secho(str(err), fg="red")
        raise typer.Exit(1)


def json_output(obj: Any) -> None:
    typer.echo(orjson.dumps(obj, option=orjson.OPT_INDENT_2).decode("utf-8"))


def print_unifi_obj(obj: ProtectBaseObject | None, output_format: OutputFormatEnum) -> None:
    """Helper method to print a single protect object"""

    if obj is not None:
        json_output(obj.unifi_dict())
    elif output_format == OutputFormatEnum.JSON:
        json_output(None)


def print_unifi_list(objs: Sequence[ProtectBaseObject]) -> None:
    """Helper method to print a list of protect objects"""

    data = [o.unifi_dict() for o in objs]
    json_output(data)


def print_unifi_dict(objs: Mapping[str, ProtectBaseObject]) -> None:
    """Helper method to print a dictionary of protect objects"""

    data = {k: v.unifi_dict() for k, v in objs.items()}
    json_output(data)


def require_device_id(ctx: typer.Context) -> None:
    """Requires device ID in context"""

    if ctx.obj.device is None:
        typer.secho("Requires a valid device ID to be selected")
        raise typer.Exit(1)


def require_no_device_id(ctx: typer.Context) -> None:
    """Requires no device ID in context"""

    if ctx.obj.device is not None:
        typer.secho("Requires no device ID to be selected")
        raise typer.Exit(1)


def list_ids(ctx: typer.Context) -> None:
    """Requires no device ID. Prints list of "id name" for each device."""

    require_no_device_id(ctx)
    objs: dict[str, ProtectAdoptableDeviceModel] = ctx.obj.devices
    to_print: list[tuple[str, str | None]] = []
    for obj in objs.values():
        name = obj.display_name
        if obj.is_adopted_by_other:
            name = f"{name} [Managed by Another Console]"
        elif obj.is_adopting:
            name = f"{name} [Adopting]"
        elif obj.can_adopt:
            name = f"{name} [Unadopted]"
        elif obj.is_rebooting:
            name = f"{name} [Restarting]"
        elif obj.is_updating:
            name = f"{name} [Updating]"
        elif not obj.is_connected:
            name = f"{name} [Disconnected]"

        to_print.append((obj.id, name))

    if ctx.obj.output_format == OutputFormatEnum.JSON:
        json_output(to_print)
    else:
        for item in to_print:
            typer.echo(f"{item[0]}\t{item[1]}")


def protect_url(ctx: typer.Context) -> None:
    """Gets UniFi Protect management URL."""

    require_device_id(ctx)
    obj: NVR | ProtectAdoptableDeviceModel = ctx.obj.device
    if ctx.obj.output_format == OutputFormatEnum.JSON:
        json_output(obj.protect_url)
    else:
        typer.echo(obj.protect_url)


def is_wired(ctx: typer.Context) -> None:
    """Returns if the device is wired or not."""

    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device
    json_output(obj.is_wired)


def is_wifi(ctx: typer.Context) -> None:
    """Returns if the device has WiFi or not."""

    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device
    json_output(obj.is_wifi)


def is_bluetooth(ctx: typer.Context) -> None:
    """Returns if the device has Bluetooth or not."""

    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device
    json_output(obj.is_bluetooth)


def bridge(ctx: typer.Context) -> None:
    """Returns bridge device if connected via Bluetooth."""

    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device
    print_unifi_obj(obj.bridge, ctx.obj.output_format)


def set_ssh(ctx: typer.Context, enabled: bool) -> None:
    """
    Sets the isSshEnabled value for device.

    May not have an effect on many device types. Only seems to work for
    Linux and BusyBox based devices (camera, light and viewport).
    """

    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device
    run(ctx, obj.set_ssh(enabled))


def set_name(ctx: typer.Context, name: Optional[str] = typer.Argument(None)) -> None:
    """Sets name for the device"""

    require_device_id(ctx)
    obj: NVR | ProtectAdoptableDeviceModel = ctx.obj.device
    run(ctx, obj.set_name(name))


def update(ctx: typer.Context, data: str) -> None:
    """
    Updates the device.

    Makes a raw PATCH request to update a device. Advanced usage and usually recommended not to use.
    """

    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device

    if obj.model is not None:
        run(ctx, obj.api.update_device(obj.model, obj.id, orjson.loads(data)))


def reboot(ctx: typer.Context, force: bool = OPTION_FORCE) -> None:
    """Reboots the device."""

    require_device_id(ctx)
    obj: NVR | ProtectAdoptableDeviceModel = ctx.obj.device

    if force or typer.confirm(f'Confirm reboot of "{obj.name}"" (id: {obj.id})'):
        run(ctx, obj.reboot())


def unadopt(ctx: typer.Context, force: bool = OPTION_FORCE) -> None:
    """Unadopt/Unmanage adopted device."""

    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device

    if force or typer.confirm(f'Confirm undopt of "{obj.name}"" (id: {obj.id})'):
        run(ctx, obj.unadopt())


def adopt(ctx: typer.Context, name: Optional[str] = typer.Argument(None)) -> None:
    """
    Adopts a device.

    By default, unadopted devices do not show up in the bootstrap. Use
    `unifi-protect -u` to show unadopted devices.
    """

    require_device_id(ctx)
    obj: ProtectAdoptableDeviceModel = ctx.obj.device

    run(ctx, obj.adopt(name))


def init_common_commands(app: typer.Typer) -> tuple[dict[str, Callable[..., Any]], dict[str, Callable[..., Any]]]:
    deviceless_commands: dict[str, Callable[..., Any]] = {}
    device_commands: dict[str, Callable[..., Any]] = {}

    deviceless_commands["list-ids"] = app.command()(list_ids)
    device_commands["protect-url"] = app.command()(protect_url)
    device_commands["is-wired"] = app.command()(is_wired)
    device_commands["is-wifi"] = app.command()(is_wifi)
    device_commands["is-bluetooth"] = app.command()(is_bluetooth)
    device_commands["bridge"] = app.command()(bridge)
    device_commands["set-ssh"] = app.command()(set_ssh)
    device_commands["set-name"] = app.command()(set_name)
    device_commands["update"] = app.command()(update)
    device_commands["reboot"] = app.command()(reboot)
    device_commands["unadopt"] = app.command()(unadopt)
    device_commands["adopt"] = app.command()(adopt)

    return deviceless_commands, device_commands
