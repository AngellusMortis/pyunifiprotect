from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from rich.progress import Progress
import typer

from pyunifiprotect import data as d
from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.cli import base
from pyunifiprotect.exceptions import NvrError
from pyunifiprotect.utils import local_datetime

app = typer.Typer(rich_markup_mode="rich")

ARG_EVENT_ID = typer.Argument(None, help="ID of camera to select for subcommands")
OPTION_START = typer.Option(None, "-s", "--start")
OPTION_END = typer.Option(None, "-e", "--end")
OPTION_LIMIT = typer.Option(None, "-l", "--limit")
OPTION_TYPES = typer.Option(None, "-t", "--type")
OPTION_SMART_TYPES = typer.Option(
    None, "-d", "--smart-detect", help="If provided, will only return smartDetectZone events"
)


@dataclass
class EventContext(base.CliContext):
    events: dict[str, d.Event] | None = None
    event: d.Event | None = None


ALL_COMMANDS: dict[str, Callable[..., None]] = {}


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    event_id: Optional[str] = ARG_EVENT_ID,
    start: Optional[datetime] = OPTION_START,
    end: Optional[datetime] = OPTION_END,
    limit: Optional[int] = OPTION_LIMIT,
    types: Optional[List[d.EventType]] = OPTION_TYPES,
    smart_types: Optional[List[d.SmartDetectObjectType]] = OPTION_SMART_TYPES,
) -> None:
    """
    Events CLI.

    Returns list of events from the last 24 hours without any arguments passed.
    """

    protect: ProtectApiClient = ctx.obj.protect
    context = EventContext(protect=ctx.obj.protect, event=None, events=None, output_format=ctx.obj.output_format)
    ctx.obj = context

    if event_id is not None and event_id not in ALL_COMMANDS:
        try:
            ctx.obj.event = base.run(ctx, protect.get_event(event_id))
        except NvrError as err:
            typer.secho("Invalid event ID", fg="red")
            raise typer.Exit(1) from err

    if not ctx.invoked_subcommand:
        if ctx.obj.event is not None:
            base.print_unifi_obj(ctx.obj.event, ctx.obj.output_format)
            return

        if types is not None and len(types) == 0:
            types = None
        if smart_types is not None and len(smart_types) == 0:
            smart_types = None
        events = base.run(
            ctx, protect.get_events(start=start, end=end, limit=limit, types=types, smart_detect_types=smart_types)
        )
        ctx.obj.events = {}
        for event in events:
            ctx.obj.events[event.id] = event

        if event_id in ALL_COMMANDS:
            ctx.invoke(ALL_COMMANDS[event_id], ctx)
            return

        base.print_unifi_dict(ctx.obj.events)


def require_event_id(ctx: typer.Context) -> None:
    """Requires event ID in context"""

    if ctx.obj.event is None:
        typer.secho("Requires a valid event ID to be selected")
        raise typer.Exit(1)


def require_no_event_id(ctx: typer.Context) -> None:
    """Requires no device ID in context"""

    if ctx.obj.event is not None or ctx.obj.events is None:
        typer.secho("Requires no event ID to be selected")
        raise typer.Exit(1)


@app.command()
def list_ids(ctx: typer.Context) -> None:
    """
    Prints list of "id type timestamp" for each event.

    Timestamps dispalyed in your locale timezone. If it is not configured
    correctly, it will default to UTC. You can override your timezone with
    the TZ environment variable.
    """

    require_no_event_id(ctx)
    objs: dict[str, d.Event] = ctx.obj.events
    to_print: list[tuple[str, str, datetime]] = []
    longest_event = 0
    for obj in objs.values():
        event_type = obj.type.value
        if event_type == d.EventType.SMART_DETECT:
            event_type = f"{event_type}[{','.join(obj.smart_detect_types)}]"
        if len(event_type) > longest_event:
            longest_event = len(event_type)
        dt = obj.timestamp or obj.start
        dt = local_datetime(dt)

        to_print.append((obj.id, event_type, dt))

    if ctx.obj.output_format == base.OutputFormatEnum.JSON:
        base.json_output(to_print)
    else:
        for item in to_print:
            typer.echo(f"{item[0]}\t{item[1]:{longest_event}}\t{item[2]}")


ALL_COMMANDS["list-ids"] = list_ids


@app.command()
def save_thumbnail(
    ctx: typer.Context,
    output_path: Path = typer.Argument(..., help="JPEG format"),
) -> None:
    """Saves thumbnail for event.

    Only for ring, motion and smartDetectZone events.
    """

    require_event_id(ctx)
    event: d.Event = ctx.obj.event

    thumbnail = base.run(ctx, event.get_thumbnail())
    if thumbnail is None:
        typer.secho("Could not get thumbnail", fg="red")
        raise typer.Exit(1)

    with open(output_path, "wb") as f:
        f.write(thumbnail)


@app.command()
def save_animated_thumbnail(
    ctx: typer.Context,
    output_path: Path = typer.Argument(..., help="GIF format"),
) -> None:
    """Saves animated thumbnail for event.

    Only for ring, motion and smartDetectZone events.
    """

    require_event_id(ctx)
    event: d.Event = ctx.obj.event

    thumbnail = base.run(ctx, event.get_animated_thumbnail())
    if thumbnail is None:
        typer.secho("Could not get thumbnail", fg="red")
        raise typer.Exit(1)

    with open(output_path, "wb") as f:
        f.write(thumbnail)


@app.command()
def save_heatmap(
    ctx: typer.Context,
    output_path: Path = typer.Argument(..., help="PNG format"),
) -> None:
    """
    Saves heatmap for event.

    Only motion events have heatmaps.
    """

    require_event_id(ctx)
    event: d.Event = ctx.obj.event

    heatmap = base.run(ctx, event.get_heatmap())
    if heatmap is None:
        typer.secho("Could not get heatmap", fg="red")
        raise typer.Exit(1)

    with open(output_path, "wb") as f:
        f.write(heatmap)


@app.command()
def save_video(
    ctx: typer.Context,
    output_path: Path = typer.Argument(..., help="MP4 format"),
    channel: int = typer.Option(0, "-c", "--channel", min=0, max=3, help="0 = High, 1 = Medium, 2 = Low, 3 = Package"),
) -> None:
    """Exports video for event.

    Only for ring, motion and smartDetectZone events.
    """

    require_event_id(ctx)
    event: d.Event = ctx.obj.event

    with Progress() as pb:
        task_id = pb.add_task("(1/2) Exporting", total=100)

        async def callback(step: int, current: int, total: int) -> None:
            pb.update(task_id, total=total, completed=current, description="(2/2) Downloading")

        base.run(
            ctx,
            event.get_video(channel, output_file=output_path, progress_callback=callback),
        )
