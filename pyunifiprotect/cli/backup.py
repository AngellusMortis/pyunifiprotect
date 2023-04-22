from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging
import math
import os
from pathlib import Path
import sys
import time
from typing import TYPE_CHECKING, Any, Optional, cast

from PIL import Image
import aiofiles
import aiofiles.os as aos
from asyncify import asyncify
import av
import dateparser
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    track,
)
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    event as saevent,
    func,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Mapped, declarative_base, relationship
import typer

from pyunifiprotect import data as d
from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.cli import base
from pyunifiprotect.utils import (
    format_duration,
    get_local_timezone,
    local_datetime,
    utc_now,
)

if TYPE_CHECKING:
    from click.core import Parameter

app = typer.Typer(rich_markup_mode="rich")
Base = declarative_base()

_LOGGER = logging.getLogger(__name__)


def _on_db_connect(dbapi_con, connection_record) -> None:  # type: ignore
    cursor = dbapi_con.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")


@dataclass
class BackupContext(base.CliContext):
    start: datetime
    end: datetime | None
    output: Path
    seperator: str
    thumbnail_format: str
    gif_format: str
    event_format: str
    title_format: str
    max_download: int
    page_size: int
    length_cutoff: timedelta
    _db_engine: AsyncEngine | None = None
    _db_session: AsyncSession | None = None

    @property
    def download_thumbnails(self) -> bool:
        return self.thumbnail_format != ""

    @property
    def download_gifs(self) -> bool:
        return self.gif_format != ""

    @property
    def download_videos(self) -> bool:
        return self.event_format != ""

    @property
    def db_file(self) -> Path:
        return self.output / "events.db"

    @property
    def db_engine(self) -> AsyncEngine:
        if self._db_engine is None:
            self._db_engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_file}")
            self._db_session = None
            saevent.listens_for(self._db_engine.sync_engine, "connect")(_on_db_connect)

        return self._db_engine

    def create_db_session(self) -> AsyncSession:
        return AsyncSession(bind=self.db_engine, expire_on_commit=False)

    async def create_db(self) -> None:
        async with self.db_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


class EventTypeChoice(str, Enum):
    MOTION = d.EventType.MOTION.value
    RING = d.EventType.RING.value
    SMART_DETECT = d.EventType.SMART_DETECT.value
    SMART_DETECT_LINE = d.EventType.SMART_DETECT_LINE.value


class EventSmartType(Base):
    __tablename__ = "event_smart_type"

    id = Column(Integer, primary_key=True)
    event_id = Column(String(24), ForeignKey("event.id"), nullable=False)
    smart_type = Column(String(32), index=True)


class Event(Base):
    __tablename__ = "event"
    __allow_unmapped__ = True

    id = Column(String(24), primary_key=True)
    start_naive = Column(DateTime())
    end_naive = Column(DateTime(), nullable=True)
    camera_mac = Column(String(12), index=True)
    event_type = Column(String(32), index=True)

    smart_detect_types: Mapped[list[EventSmartType]] = relationship("EventSmartType", lazy="joined", uselist=True)

    _start: datetime | None = None
    _end: datetime | None = None
    _smart_types: set[str] | None = None
    _context: dict[str, str] | None = None
    _glob_context: dict[str, str] | None = None

    @property
    def start(self) -> datetime:
        if self._start is None:
            self._start = self.start_naive.replace(tzinfo=timezone.utc)  # type: ignore
        return self._start

    @property
    def end(self) -> datetime | None:
        if self._end is None:
            if self.end_naive is not None:
                self._end = self.end_naive.replace(tzinfo=timezone.utc)
        return self._end

    @property
    def smart_types(self) -> set[str]:
        if self._smart_types is None:
            self._smart_types = {s.smart_type for s in self.smart_detect_types}  # type: ignore
        return self._smart_types

    def get_file_context(self, ctx: BackupContext) -> dict[str, str]:
        if self._context is None:
            camera = ctx.protect.bootstrap.get_device_from_mac(self.camera_mac)  # type: ignore
            camera_slug = ""
            display_name = ""
            length = timedelta(seconds=0)
            if camera is not None:
                camera_slug = camera.display_name.lower().replace(" ", ctx.seperator) + ctx.seperator
                display_name = camera.display_name
            if self.end is not None:
                length = self.end - self.start

            event_type = str(self.event_type)
            event_type_pretty = f"{event_type.title()} Event"
            if event_type in (d.EventType.SMART_DETECT.value, d.EventType.SMART_DETECT_LINE.value):
                smart_types = list(self.smart_types)
                smart_types.sort()
                event_type = f"{event_type}[{','.join(smart_types)}]"
                smart_types_title = [s.title() for s in smart_types]
                event_type_pretty = f"Smart Detection ({', '.join(smart_types_title)})"

            start_local = local_datetime(self.start)
            self._context = {
                "year": str(self.start.year),
                "month": str(self.start.month),
                "day": str(self.start.day),
                "hour": str(self.start.hour),
                "minute": str(self.start.minute),
                "datetime": self.start.strftime("%Y-%m-%dT%H-%M-%S%z").replace("-", ctx.seperator),
                "date": self.start.strftime("%Y-%m-%d").replace("-", ctx.seperator),
                "time": self.start.strftime("%H-%M-%S%z").replace("-", ctx.seperator),
                "time_sort_pretty": self.start.strftime("%H:%M:%S (%Z)"),
                "time_pretty": self.start.strftime("%I:%M:%S %p (%Z)"),
                "year_local": str(start_local.year),
                "month_local": str(start_local.month),
                "day_local": str(start_local.day),
                "hour_local": str(start_local.hour),
                "minute_local": str(start_local.minute),
                "datetime_local": start_local.strftime("%Y-%m-%dT%H-%M-%S%z").replace("-", ctx.seperator),
                "date_local": start_local.strftime("%Y-%m-%d").replace("-", ctx.seperator),
                "time_local": start_local.strftime("%H-%M-%S%z").replace("-", ctx.seperator),
                "time_sort_pretty_local": start_local.strftime("%H:%M:%S (%Z)"),
                "time_pretty_local": start_local.strftime("%I:%M:%S %p (%Z)"),
                "mac": str(self.camera_mac),
                "camera_name": display_name,
                "camera_slug": camera_slug,
                "event_type": event_type,
                "event_type_pretty": event_type_pretty,
                "length_pretty": format_duration(length),
                "sep": ctx.seperator,
            }

            self._context["title"] = ctx.title_format.format(**self._context)
        return self._context

    def get_glob_file_context(self, ctx: BackupContext) -> dict[str, str]:
        if self._glob_context is None:
            self._glob_context = self.get_file_context(ctx).copy()
            self._glob_context["camera_slug"] = "*"
            self._glob_context["camera_name"] = "*"
        return self._glob_context

    def get_thumbnail_path(self, ctx: BackupContext) -> Path:
        context = self.get_file_context(ctx)
        file_path = ctx.thumbnail_format.format(**context)
        return ctx.output / file_path

    def get_existing_thumbnail_path(self, ctx: BackupContext) -> Path | None:
        context = self.get_glob_file_context(ctx)
        file_path = ctx.thumbnail_format.format(**context)

        paths = list(ctx.output.glob(file_path))
        if paths:
            return paths[0]
        return None

    def get_gif_path(self, ctx: BackupContext) -> Path:
        context = self.get_file_context(ctx)
        file_path = ctx.gif_format.format(**context)
        return ctx.output / file_path

    def get_existing_gif_path(self, ctx: BackupContext) -> Path | None:
        context = self.get_glob_file_context(ctx)
        file_path = ctx.gif_format.format(**context)

        paths = list(ctx.output.glob(file_path))
        if paths:
            return paths[0]
        return None

    def get_event_path(self, ctx: BackupContext) -> Path:
        context = self.get_file_context(ctx)
        file_path = ctx.event_format.format(**context)
        return ctx.output / file_path

    def get_existing_event_path(self, ctx: BackupContext) -> Path | None:
        context = self.get_glob_file_context(ctx)
        file_path = ctx.event_format.format(**context)

        paths = list(ctx.output.glob(file_path))
        if paths:
            return paths[0]
        return None


@dataclass
class QueuedDownload:
    task: asyncio.Task[bool] | None
    args: list[Any]


def relative_datetime(ctx: typer.Context, value: str, param: Parameter) -> datetime:
    if dt := dateparser.parse(value):
        return dt

    raise typer.BadParameter("Must be a ISO 8601 format or human readable relative format", ctx, param)


_DownloadEventQueue = asyncio.Queue[QueuedDownload]

OPTION_OUTPUT = typer.Option(None, help="Base dir for creating files. Defaults to $PWD.", envvar="UFP_BACKUP_OUTPUT")
OPTION_START = typer.Option(
    None,
    "-s",
    "--start",
    help="Cutoff for start of backup. Defaults to start of recording for NVR.",
    envvar="UFP_BACKUP_START",
)
OPTION_PAGE_SIZE = typer.Option(
    1000, "--page-size", help="Number of events fetched at once from local database. Increases memory usage."
)
OPTION_LENGTH_CUTOFF = typer.Option(
    timedelta(hours=1).total_seconds(),
    "--length-cutoff",
    help="Event size cutoff for detecting abnormal events (in seconds).",
)
OPTION_END = typer.Option(
    None, "-e", "--end", help="Cutoff for end of backup. Defaults to now.", envvar="UFP_BACKUP_END"
)
OPTION_EVENT_TYPES = typer.Option(
    list(EventTypeChoice), "-t", "--event-type", help="Events to export. Can be used multiple time."
)
OPTION_SMART_TYPES = typer.Option(
    list(d.SmartDetectObjectType),
    "-m",
    "--smart-type",
    help="Smart Detection types to export. Can be used multiple time.",
)
OPTION_SPERATOR = typer.Option("-", "--sep", help="Separator used for formatting.")
OPTION_THUMBNAIL_FORMAT = typer.Option(
    "{year}/{month}/{day}/{hour}/{datetime}{sep}{mac}{sep}{camera_slug}{event_type}{sep}thumb.jpg",
    "--thumb-format",
    help='Filename format to save event thumbnails to. Set to empty string ("") to skip saving event thumbnails.',
)
OPTION_GIF_FORMAT = typer.Option(
    "{year}/{month}/{day}/{hour}/{datetime}{sep}{mac}{sep}{camera_slug}{event_type}{sep}animated.gif",
    "--gif-format",
    help='Filename format to save event gifs to. Set to empty string ("") to skip saving event gif.',
)
OPTION_EVENT_FORMAT = typer.Option(
    "{year}/{month}/{day}/{hour}/{datetime}{sep}{mac}{sep}{camera_slug}{event_type}.mp4",
    "--event-format",
    help='Filename format to save event gifs to. Set to empty string ("") to skip saving event videos.',
)
OPTION_TITLE_FORMAT = typer.Option(
    "{time_sort_pretty_local} {sep} {camera_name} {sep} {event_type_pretty} {sep} {length_pretty}",
    "--title-format",
    help="Format to use to tag title for video metadata.",
)
OPTION_VERBOSE = typer.Option(False, "-v", "--verbose", help="Debug logging.")
OPTION_MAX_DOWNLOAD = typer.Option(
    5, "-d", "--max-download", help="Max number of concurrent downloads. Adds additional loads to NVR."
)


def _setup_logger(verbose: bool) -> None:
    console_handler = logging.StreamHandler()
    log_format = "[%(asctime)s] %(levelname)s - %(message)s"
    if verbose:
        console_handler.setLevel(logging.DEBUG)
    elif sys.stdout.isatty():
        console_handler.setLevel(logging.WARN)
        log_format = "%(message)s"
    else:
        console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(log_format)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger("pyunifiprotect")
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)


@app.callback()
def main(
    ctx: typer.Context,
    start: Optional[str] = OPTION_START,
    end: Optional[str] = OPTION_END,
    output_folder: Optional[Path] = OPTION_OUTPUT,
    thumbnail_format: str = OPTION_THUMBNAIL_FORMAT,
    gif_format: str = OPTION_GIF_FORMAT,
    event_format: str = OPTION_EVENT_FORMAT,
    title_format: str = OPTION_TITLE_FORMAT,
    verbose: bool = OPTION_VERBOSE,
    max_download: int = OPTION_MAX_DOWNLOAD,
    page_size: int = OPTION_PAGE_SIZE,
    length_cutoff: int = OPTION_LENGTH_CUTOFF,
    seperator: str = OPTION_SPERATOR,
) -> None:
    """
    Backup CLI.

    The backup CLI is still very WIP in progress and consider experimental and potentially unstable (interface may change in the future).
    """

    _setup_logger(verbose)

    protect: ProtectApiClient = ctx.obj.protect
    local_tz = get_local_timezone()

    if start is None:
        start_dt = protect.bootstrap.recording_start
    else:
        start_dt = relative_datetime(ctx, start, ctx.command.params[0])
        start_dt = start_dt.replace(tzinfo=local_tz)
    if start_dt is None:
        start_dt = utc_now()

    end_dt = None
    if end is not None:
        end_dt = relative_datetime(ctx, end, ctx.command.params[1])
        end_dt = end_dt.replace(tzinfo=local_tz)

    if output_folder is None:
        output_folder = Path(os.getcwd())

    context = BackupContext(
        protect=ctx.obj.protect,
        start=start_dt,
        end=end_dt,
        output_format=ctx.obj.output_format,
        output=output_folder,
        thumbnail_format=thumbnail_format,
        gif_format=gif_format,
        event_format=event_format,
        title_format=title_format,
        max_download=max_download,
        page_size=page_size,
        length_cutoff=timedelta(seconds=length_cutoff),
        seperator=seperator,
    )
    ctx.obj = context


def _wipe_files(ctx: BackupContext, no_input: bool) -> None:
    if not no_input:
        if not typer.confirm("Are you sure you want to delete all existing thumbnails and video clips?"):
            raise typer.Exit(1)

    if ctx.db_file.exists():
        os.remove(ctx.db_file)

    for path in track(ctx.output.glob("**/*.jpg"), description="Deleting Thumbnails"):
        os.remove(path)

    for path in track(ctx.output.glob("**/*.mp4"), description="Deleting Clips"):
        os.remove(path)


async def _newest_event(ctx: BackupContext) -> Event | None:
    db = ctx.create_db_session()
    async with db:
        result = await db.execute(select(Event).order_by(Event.start_naive.desc()))
        return result.scalars().first()


async def _prune_events(ctx: BackupContext) -> int:
    _LOGGER.debug("Pruning events before %s", ctx.start)

    deleted = 0
    db = ctx.create_db_session()
    async with db:
        result = await db.execute(select(Event).join(EventSmartType).where(Event.start_naive < ctx.start))
        for event in track(result.unique().scalars(), description="Pruning Events"):
            thumb_path = event.get_thumbnail_path(ctx)
            if thumb_path.exists():
                _LOGGER.debug("Delete file %s", thumb_path)
                await aos.remove(thumb_path)

            event_path = event.get_event_path(ctx)
            if event_path.exists():
                _LOGGER.debug("Delete file %s", event_path)
                await aos.remove(event_path)

            if event.event_type in (d.EventType.SMART_DETECT.value, d.EventType.SMART_DETECT_LINE.value):
                for smart_type in event.smart_detect_types:
                    await db.delete(smart_type)
            await db.delete(event)
            deleted += 1
        await db.commit()

    return deleted


async def _update_event(ctx: BackupContext, event: d.Event) -> None:
    if event.camera is None:
        return

    db = ctx.create_db_session()
    to_delete: list[EventSmartType] = []
    async with db:
        result = await db.execute(select(Event).where(Event.id == event.id))
        db_event = result.scalars().first()
        do_insert = False
        if db_event is None:
            db_event = Event(id=event.id)
            do_insert = True
        db_event.start_naive = event.start
        db_event.end_naive = event.end
        db_event.camera_mac = event.camera.mac
        db_event.event_type = event.type.value

        if event.type in (d.EventType.SMART_DETECT.value, d.EventType.SMART_DETECT_LINE.value):
            types = {e.value for e in event.smart_detect_types}

            result = await db.execute(select(EventSmartType).where(EventSmartType.event_id == event.id))
            for event_smart_type in result.unique().scalars():
                event_type = cast(EventSmartType, event_smart_type)
                if event_type.smart_type not in types:
                    to_delete.append(event_type)
                else:
                    types.remove(event_type.smart_type)

            for smart_type_str in types:
                db.add(EventSmartType(event_id=event.id, smart_type=smart_type_str))

        if do_insert:
            db.add(db_event)
        for smart_type in to_delete:
            await db.delete(smart_type)
        await db.commit()


async def _update_ongoing_events(ctx: BackupContext) -> int:
    db = ctx.create_db_session()
    async with db:
        result = await db.execute(select(Event).where(Event.event_type != "ring").where(Event.end_naive is None))  # type: ignore

        events = list(result.unique().scalars())

    if len(events) == 0:
        return 0
    for event in track(events, description="Updating Events"):
        event_id = cast(str, event.id)
        await _update_event(ctx, await ctx.protect.get_event(event_id))
    return len(events)


async def _update_events(ctx: BackupContext) -> int:
    # update any events that are still set as ongoing in the database
    updated_ongoing = await _update_ongoing_events(ctx)
    start = ctx.start
    end = ctx.end or utc_now()
    processed: set[str] = set()

    total = int((end - ctx.start).total_seconds())
    _LOGGER.debug("total: %s: %s %s", total, start, end)

    prev_start = start
    with Progress() as pb:
        task_id = pb.add_task("Fetching New Events", total=total)
        task = pb.tasks[0]
        pb.refresh()
        while not pb.finished:
            progress = int((start - prev_start).total_seconds())
            pb.update(task_id, advance=progress)
            _LOGGER.debug("progress: +%s: %s/%s: %s %s", progress, task.completed, task.total, start, end)

            events = await ctx.protect.get_events(
                start,
                end,
                limit=100,
                types=[d.EventType.MOTION, d.EventType.RING, d.EventType.SMART_DETECT, d.EventType.SMART_DETECT_LINE],
            )

            prev_start = start
            count = 0
            for event in events:
                start = event.start
                if event.id not in processed:
                    count += 1
                    processed.add(event.id)
                    await _update_event(ctx, event)

            if start == prev_start and count == 0:
                pb.update(task_id, completed=total)

    return updated_ongoing + len(processed)


async def _download_watcher(count: int, tasks: _DownloadEventQueue, no_error_flag: asyncio.Event) -> int:
    processed = 0
    loop = asyncio.get_running_loop()
    downloaded = 0
    last_print = time.monotonic()
    while processed < count:
        download = await tasks.get()
        task = download.task
        if task is None:
            processed += 1
            continue

        retries = 0
        while True:
            try:
                await task
            except asyncio.CancelledError:
                return downloaded
            except Exception:  # pylint: disable=broad-except
                pass

            event: Event = download.args[1]
            if exception := task.exception():
                no_error_flag.clear()
                if retries < 5:
                    wait = math.pow(2, retries)
                    _LOGGER.warning(
                        "Exception while downloading event (%s): %s. Retring in %s second(s)", event.id, exception, wait
                    )
                    await asyncio.sleep(wait)
                    retries += 1
                    task = loop.create_task(_download_event(*download.args))
                else:
                    _LOGGER.error("Failed to download event %s", event.id)

            if exception is None or retries >= 5:
                no_error_flag.set()
                processed += 1
                now = time.monotonic()
                if now - last_print > 60:
                    _LOGGER.info("Processed %s/%s (%.2f%%) events", processed, count, processed / count)
                    last_print = now
                if exception is None and task.result():
                    downloaded += 1
                break
    return downloaded


@asyncify
def _verify_thumbnail(path: Path) -> bool:
    try:
        image = Image.open(path)
        image.verify()
    # no docs on what exception could be
    except Exception:  # pylint: disable=broad-except
        return False
    return True


async def _download_event_thumb(
    ctx: BackupContext, event: Event, verify: bool, force: bool, animated: bool = False
) -> bool:
    if animated:
        thumb_type = "gif"
        thumb_path = event.get_gif_path(ctx)
        existing_thumb_path = event.get_existing_gif_path(ctx)
    else:
        thumb_type = "thumbnail"
        thumb_path = event.get_thumbnail_path(ctx)
        existing_thumb_path = event.get_existing_thumbnail_path(ctx)

    if force and existing_thumb_path:
        _LOGGER.debug("Delete file %s", existing_thumb_path)
        await aos.remove(existing_thumb_path)

    if existing_thumb_path and str(existing_thumb_path) != str(thumb_path):
        _LOGGER.debug(
            "Rename event %s file %s: %s %s %s: %s",
            thumb_type,
            event.id,
            event.start,
            event.end,
            event.event_type,
            thumb_path,
        )
        await aos.makedirs(thumb_path.parent, exist_ok=True)
        await aos.rename(existing_thumb_path, thumb_path)

    if verify and thumb_path.exists() and not await _verify_thumbnail(thumb_path):
        _LOGGER.warning("Corrupted event %s file for event (%s), redownloading", thumb_type, event.id)
        await aos.remove(thumb_path)

    if not thumb_path.exists():
        _LOGGER.debug(
            "Download event %s %s: %s %s: %s", thumb_type, event.id, event.start, event.event_type, thumb_path
        )
        event_id = str(event.id)
        if animated:
            thumbnail = await ctx.protect.get_event_animated_thumbnail(event_id)
        else:
            thumbnail = await ctx.protect.get_event_thumbnail(event_id)
        if thumbnail is not None:
            await aos.makedirs(thumb_path.parent, exist_ok=True)
            async with aiofiles.open(thumb_path, mode="wb") as f:
                await f.write(thumbnail)
            return True
    return False


@asyncify
def _verify_video_file(path: Path, length: float, width: int, height: int, title: str) -> tuple[bool, bool]:
    try:
        with av.open(str(path)) as video:
            slength = float(video.streams.video[0].duration * video.streams.video[0].time_base)
            valid = (
                (slength / length) > 0.80  # export is fuzzy
                and video.streams.video[0].codec_context.width == width
                and video.streams.video[0].codec_context.height == height
            )
            metadata_valid = False
            if valid:
                metadata_valid = bool(video.metadata["title"] == title)
            return valid, metadata_valid

    # no docs on what exception could be
    except Exception:  # pylint: disable=broad-except
        return False, False


@asyncify
def _add_metadata(path: Path, creation: datetime, title: str) -> bool:
    creation = local_datetime(creation)
    output_path = path.parent / path.name.replace(".mp4", ".metadata.mp4")

    success = True
    try:
        with av.open(str(path)) as input_file:
            with av.open(str(output_path), "w") as output_file:
                for key, value in input_file.metadata.items():
                    output_file.metadata[key] = value
                output_file.metadata["creation_time"] = creation.isoformat()
                output_file.metadata["title"] = title
                output_file.metadata["year"] = creation.date().isoformat()
                output_file.metadata["release"] = creation.date().isoformat()

                in_to_out: dict[str, Any] = {}
                for stream in input_file.streams:
                    in_to_out[stream] = output_file.add_stream(template=stream)
                    in_to_out[stream].metadata["creation_time"] = creation.isoformat()

                for packet in input_file.demux(list(in_to_out.keys())):
                    if packet.dts is None:
                        continue

                    packet.stream = in_to_out[packet.stream]
                    try:
                        output_file.mux(packet)
                    # some frames may be corrupted on disk from NVR
                    except ValueError:
                        continue
    # no docs on what exception could be
    except Exception:  # pylint: disable=broad-except
        success = False
    finally:
        if success:
            os.remove(path)
            output_path.rename(path)
        elif output_path.exists():
            os.remove(output_path)
    return success


async def _download_event_video(ctx: BackupContext, camera: d.Camera, event: Event, verify: bool, force: bool) -> bool:
    event_path = event.get_event_path(ctx)
    existing_event_path = event.get_existing_event_path(ctx)
    if force and existing_event_path:
        _LOGGER.debug("Delete file %s", existing_event_path)
        await aos.remove(existing_event_path)

    if existing_event_path and str(existing_event_path) != str(event_path):
        _LOGGER.debug(
            "Rename event file %s: %s %s %s: %s", event.id, event.start, event.end, event.event_type, event_path
        )
        await aos.makedirs(event_path.parent, exist_ok=True)
        await aos.rename(existing_event_path, event_path)

    metadata_valid = True
    if verify and event_path.exists():
        valid = False
        if event.end is not None:
            valid, metadata_valid = await _verify_video_file(
                event_path,
                (event.end - event.start).total_seconds(),
                camera.channels[0].width,
                camera.channels[0].height,
                event.get_file_context(ctx)["title"],
            )

        if not valid:
            _LOGGER.warning("Corrupted video file for event (%s), redownloading", event.id)
            await aos.remove(event_path)

    downloaded = False
    if not event_path.exists() and event.end is not None:
        _LOGGER.debug("Download event %s: %s %s %s: %s", event.id, event.start, event.end, event.event_type, event_path)
        await aos.makedirs(event_path.parent, exist_ok=True)
        await camera.get_video(event.start, event.end, output_file=event_path)
        downloaded = True

    if (downloaded or not metadata_valid) and event.end is not None:
        file_context = event.get_file_context(ctx)
        if not await _add_metadata(event_path, event.start, file_context["title"]):
            _LOGGER.warning("Failed to write metadata for event (%s)", event.id)
    return downloaded


async def _download_event(ctx: BackupContext, event: Event, verify: bool, force: bool, pb: Progress) -> bool:
    downloaded = False
    camera = ctx.protect.bootstrap.get_device_from_mac(event.camera_mac)  # type: ignore
    if camera is not None:
        camera = cast(d.Camera, camera)
        downloads = []
        if ctx.download_thumbnails:
            downloads.append(_download_event_thumb(ctx, event, verify, force))
        if ctx.download_gifs:
            downloads.append(_download_event_thumb(ctx, event, verify, force, animated=True))
        if ctx.download_thumbnails:
            downloads.append(_download_event_video(ctx, camera, event, verify, force))

        downloaded = any(await asyncio.gather(*downloads))
    pb.update(pb.tasks[0].id, advance=1)
    return downloaded


async def _download_events(
    ctx: BackupContext,
    event_types: list[d.EventType],
    smart_types: list[d.SmartDetectObjectType],
    verify: bool,
    force: bool,
) -> tuple[int, int]:
    start = ctx.start
    end = ctx.end or utc_now()
    db = ctx.create_db_session()
    async with db:
        count_query = (
            select(func.count(Event.id))  # pylint: disable=not-callable
            .where(Event.event_type.in_([e.value for e in event_types]))
            .where(Event.start_naive >= start)
            .where(or_(Event.end_naive <= end, Event.end_naive is None))  # type: ignore
        )
        count = cast(int, (await db.execute(count_query)).scalar())
        _LOGGER.info("Downloading %s events", count)

        columns = [
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeRemainingColumn(),
        ]
        with Progress(*columns) as pb:
            task_id = pb.add_task("Downloading Events", total=count)

            query = (
                select(Event)
                .where(Event.event_type.in_([e.value for e in event_types]))
                .where(Event.start_naive >= start)
                .where(or_(Event.end_naive <= end, Event.end_naive is None))  # type: ignore
                .limit(ctx.page_size)
            )
            smart_types_set = {s.value for s in smart_types}
            loop = asyncio.get_running_loop()
            tasks: _DownloadEventQueue = asyncio.Queue(maxsize=ctx.max_download - 1)
            no_error_flag = asyncio.Event()
            no_error_flag.set()
            watcher_task = loop.create_task(_download_watcher(count, tasks, no_error_flag))

            offset = 0
            page = query
            while offset < count:
                result = await db.execute(page)
                for event in result.unique().scalars():
                    if event.end is None:
                        continue

                    length = event.end - event.start
                    if length > ctx.length_cutoff:
                        _LOGGER.warning("Skipping event %s because it is too long (%s)", event.id, length)
                        await tasks.put(QueuedDownload(task=None, args=[]))
                        continue
                    # ensure no tasks are currently in a retry state
                    await no_error_flag.wait()

                    if event.event_type in (d.EventType.SMART_DETECT.value, d.EventType.SMART_DETECT_LINE.value):
                        if not event.smart_types.intersection(smart_types_set):
                            continue

                    task = loop.create_task(_download_event(ctx, event, verify, force, pb))
                    # waits for a free processing slot
                    await tasks.put(QueuedDownload(task=task, args=[ctx, event, verify, force, pb]))

                offset += ctx.page_size
                page = query.offset(offset)

            try:
                await watcher_task
                downloaded = watcher_task.result()
            except asyncio.CancelledError:
                downloaded = 0
            pb.update(task_id, completed=count)
    return count, downloaded


async def _events(
    ctx: BackupContext,
    event_types: list[d.EventType],
    smart_types: list[d.SmartDetectObjectType],
    prune: bool,
    force: bool,
    verify: bool,
    no_input: bool,
) -> None:
    try:
        await ctx.create_db()

        if prune and not force:
            _LOGGER.warning("Pruned %s old event(s)", await _prune_events(ctx))

        original_start = ctx.start
        if not force:
            event = await _newest_event(ctx)
            if event is not None:
                ctx.start = event.start

        _LOGGER.warning("Updated %s event(s)", await _update_events(ctx))
        ctx.start = original_start
        count, downloaded = await _download_events(ctx, event_types, smart_types, verify, force)
        verified = count - downloaded
        _LOGGER.warning(
            "Total events: %s. Verified %s existing event(s). Downloaded %s new event(s)", count, verified, downloaded
        )
    finally:
        _LOGGER.debug("Cleaning up Protect connection/database...")
        await ctx.protect.close_session()
        await ctx.db_engine.dispose()


@app.command(name="events")
def events_cmd(
    ctx: typer.Context,
    event_types: list[EventTypeChoice] = OPTION_EVENT_TYPES,
    smart_types: list[d.SmartDetectObjectType] = OPTION_SMART_TYPES,
    prune: bool = typer.Option(False, "-p", "--prune", help="Prune events older then start."),
    force: bool = typer.Option(False, "-f", "--force", help="Force update all events and redownload all clips."),
    verify: bool = typer.Option(False, "-v", "--verify", help="Verifies files on disk."),
    no_input: bool = typer.Option(False, "--no-input"),
) -> None:
    """Backup thumbnails and video clips for camera events."""

    # surpress av logging messages
    av.logging.set_level(av.logging.PANIC)  # pylint: disable=c-extension-no-member
    ufp_events = [d.EventType(e.value) for e in event_types]
    if prune and force:
        _wipe_files(ctx.obj, no_input)
    asyncio.run(_events(ctx.obj, ufp_events, smart_types, prune, force, verify, no_input))
