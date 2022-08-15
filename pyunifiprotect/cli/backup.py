from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Optional, cast

import aiofiles
import aiofiles.os as aos
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
from sqlalchemy.orm import declarative_base, relationship
import typer

from pyunifiprotect import data as d
from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.cli import base
from pyunifiprotect.utils import utc_now

if TYPE_CHECKING:
    from click._termui_impl import ProgressBar

app = typer.Typer()
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
    event_format: str
    max_download: int
    _db_engine: AsyncEngine | None = None
    _db_session: AsyncSession | None = None

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


class EventSmartType(Base):
    __tablename__ = "event_smart_type"

    id = Column(Integer, primary_key=True)
    event_id = Column(String(24), ForeignKey("event.id"), nullable=False)
    smart_type = Column(String(32), index=True)


class Event(Base):
    __tablename__ = "event"

    id = Column(String(24), primary_key=True)
    start_naive = Column(DateTime())
    end_naive = Column(DateTime(), nullable=True)
    camera_mac = Column(String(12), index=True)
    event_type = Column(String(32), index=True)

    smart_detect_types: list[EventSmartType] = relationship("EventSmartType", lazy="joined", uselist=True)

    _start: datetime | None = None
    _end: datetime | None = None
    _smart_types: set[str] | None = None
    _context: dict[str, str] | None = None

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
            if camera is not None:
                camera_slug = camera.display_name.lower().replace(" ", ctx.seperator) + ctx.seperator
            event_type = self.event_type
            if event_type == d.EventType.SMART_DETECT.value:
                smart_types = list(self.smart_types)
                smart_types.sort()
                event_type = f"{event_type}[{','.join(smart_types)}]"

            self._context = {
                "year": str(self.start.year),
                "month": str(self.start.month),
                "day": str(self.start.day),
                "datetime": self.start.strftime("%Y-%m-%dT%H-%M-%S+0000"),
                "time": self.start.strftime("%H-%M-%S+0000"),
                "mac": str(self.camera_mac),
                "camera_slug": camera_slug,
                "event_type": str(event_type),
                "sep": ctx.seperator,
            }
        return self._context

    def get_thumbnail_path(self, ctx: BackupContext) -> Path:
        context = self.get_file_context(ctx)
        file_path = ctx.thumbnail_format.format(**context)
        return ctx.output / file_path

    def get_event_path(self, ctx: BackupContext) -> Path:
        context = self.get_file_context(ctx)
        file_path = ctx.event_format.format(**context)
        return ctx.output / file_path


OPTION_OUTPUT = typer.Option(None, help="Base dir for creating files. Defaults to PWD", envvar="UFP_BACKUP_OUTPUT")
OPTION_START = typer.Option(
    None, "-s", "--start", help="Defaults to start of recording for NVR", envvar="UFP_BACKUP_START"
)
OPTION_END = typer.Option(None, "-e", "--end", help="Defaults to now", envvar="UFP_BACKUP_END")
OPTION_EVENT_TYPES = typer.Option(list(EventTypeChoice), "-t", "--event-type")
OPTION_SMART_TYPES = typer.Option(list(d.SmartDetectObjectType), "-m", "--smart-type")
OPTION_SPERATOR = typer.Option("-", "--sep")
OPTION_THUMBNAIL_FORMAT = typer.Option(
    "{year}/{month}/{day}/{datetime}{sep}{mac}{sep}{camera_slug}{event_type}{sep}thumb.jpg", "--thumb-format"
)
OPTION_EVENT_FORMAT = typer.Option(
    "{year}/{month}/{day}/{datetime}{sep}{mac}{sep}{camera_slug}{event_type}.mp4", "--event-format"
)
OPTION_VERBOSE = typer.Option(False, "-v", "--verbose", help="Debug logging")
OPTION_MAX_DOWNLOAD = typer.Option(10, "-d", "--max-download", help="Max number of concurrent downloads")


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
    start: Optional[datetime] = OPTION_START,
    end: Optional[datetime] = OPTION_END,
    output_folder: Optional[Path] = OPTION_OUTPUT,
    thumbnail_format: str = OPTION_THUMBNAIL_FORMAT,
    event_format: str = OPTION_EVENT_FORMAT,
    verbose: bool = OPTION_VERBOSE,
    max_download: int = OPTION_MAX_DOWNLOAD,
    seperator: str = OPTION_SPERATOR,
) -> None:
    """Backup your UniFi Protect Cameras."""

    _setup_logger(verbose)

    protect: ProtectApiClient = ctx.obj.protect
    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    if start is None:
        start = protect.bootstrap.recording_start
    else:
        start = start.replace(tzinfo=local_tz)
    if start is None:
        start = utc_now()
    if end is not None:
        end = end.replace(tzinfo=local_tz)
    if output_folder is None:
        output_folder = Path(os.getcwd())

    context = BackupContext(
        protect=ctx.obj.protect,
        start=start,
        end=end,
        output_format=ctx.obj.output_format,
        output=output_folder,
        thumbnail_format=thumbnail_format,
        event_format=event_format,
        max_download=max_download,
        seperator=seperator,
    )
    ctx.obj = context


def _wipe_files(ctx: BackupContext, no_input: bool) -> None:
    if not no_input:
        if not typer.confirm("Are you sure you want to delete all existing thumbnails and video clips?"):
            raise typer.Exit(1)

    if ctx.db_file.exists():
        os.remove(ctx.db_file)

    with typer.progressbar(ctx.output.glob("**/*.jpg"), label="Deleting Thumbnails") as pb:
        for path in pb:
            os.remove(path)

    with typer.progressbar(ctx.output.glob("**/*.mp4"), label="Deleting Clips") as pb:
        for path in pb:
            os.remove(path)


async def _newest_event(ctx: BackupContext) -> Event | None:
    db = ctx.create_db_session()
    async with db:
        result = await db.execute(select(Event).order_by(Event.start_naive.desc()))
        return cast(Event | None, result.scalars().first())


async def _prune_events(ctx: BackupContext) -> int:
    _LOGGER.debug("Pruning events before %s", ctx.start)

    deleted = 0
    db = ctx.create_db_session()
    async with db:
        result = await db.execute(select(Event).join(EventSmartType).where(Event.start_naive < ctx.start))
        with typer.progressbar(result.unique().scalars(), label="Pruning Events") as pb:
            for event in pb:
                event = cast(Event, event)

                thumb_path = event.get_thumbnail_path(ctx)
                if thumb_path.exists():
                    _LOGGER.debug("Delete file %s", thumb_path)
                    await aos.remove(thumb_path)

                event_path = event.get_event_path(ctx)
                if event_path.exists():
                    _LOGGER.debug("Delete file %s", event_path)
                    await aos.remove(event_path)

                if event.event_type == d.EventType.SMART_DETECT:
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
        db_event = cast(Event | None, result.scalars().first())
        do_insert = False
        if db_event is None:
            db_event = Event(id=event.id)
            do_insert = True
        db_event.start_naive = event.start
        db_event.end_naive = event.end
        db_event.camera_mac = event.camera.mac
        db_event.event_type = event.type.value

        if event.type == d.EventType.SMART_DETECT:
            types = {e.value for e in event.smart_detect_types}

            result = await db.execute(select(EventSmartType).where(EventSmartType.event_id == event.id))
            for event_type in result.unique().scalars():
                event_type = cast(EventSmartType, event_type)
                if event_type.smart_type not in types:
                    to_delete.append(event_type)
                else:
                    types.remove(event_type.smart_type)

            for event_type in types:
                db.add(EventSmartType(event_id=event.id, smart_type=event_type))

        if do_insert:
            db.add(db_event)
        for event_type in to_delete:
            await db.delete(event_type)
        await db.commit()


async def _update_events(ctx: BackupContext) -> int:
    start = ctx.start
    end = ctx.end or utc_now()
    processed: set[str] = set()

    total = int((end - ctx.start).total_seconds())
    _LOGGER.debug("total: %s: %s %s", total, start, end)
    pb: ProgressBar[None] = typer.progressbar(None, length=total, label="Updating Events")
    pb.render_progress()

    prev_start = start
    while True:
        progress = int((start - prev_start).total_seconds())
        pb.update(progress)
        _LOGGER.debug("progress: +%s: %s/%s: %s %s", progress, pb.pos, pb.length, start, end)

        events = await ctx.protect.get_events(
            start,
            end,
            limit=100,
            types=[d.EventType.MOTION, d.EventType.RING, d.EventType.SMART_DETECT],
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
            break

    pb.pos = total
    pb.render_progress()
    pb.render_finish()

    return len(processed)


async def _download_event(
    ctx: BackupContext, event: Event, force: bool, pb: ProgressBar[None], sem: asyncio.Semaphore
) -> None:

    async with sem:
        camera = ctx.protect.bootstrap.get_device_from_mac(event.camera_mac)  # type: ignore
        if camera is not None:
            camera = cast(d.Camera, camera)

            thumb_path = event.get_thumbnail_path(ctx)
            if force and thumb_path.exists():
                _LOGGER.debug("Delete file %s", thumb_path)
                await aos.remove(thumb_path)
            if not thumb_path.exists():
                _LOGGER.debug("Download thumbnail %s: %s %s: %s", event.id, event.start, event.event_type, thumb_path)
                thumbnail = await ctx.protect.get_event_thumbnail(event.id)  # type: ignore
                if thumbnail is not None:
                    await aos.makedirs(thumb_path.parent, exist_ok=True)
                    async with aiofiles.open(thumb_path, mode="wb") as f:
                        await f.write(thumbnail)

            event_path = event.get_event_path(ctx)
            if force and event_path.exists():
                _LOGGER.debug("Delete file %s", event_path)
                await aos.remove(event_path)
            if not event_path.exists() and event.end is not None:
                _LOGGER.debug(
                    "Download event %s: %s %s %s: %s", event.id, event.start, event.end, event.event_type, event_path
                )
                await aos.makedirs(event_path.parent, exist_ok=True)
                await camera.get_video(event.start, event.end, output_file=event_path)
    pb.update(1)


async def _download_events(
    ctx: BackupContext, event_types: list[d.EventType], smart_types: list[d.SmartDetectObjectType], force: bool
) -> int:
    start = ctx.start
    end = ctx.end or utc_now()
    downloaded = 0
    db = ctx.create_db_session()
    async with db:
        count_query = (
            select(func.count(Event.id))
            .where(Event.event_type.in_([e.value for e in event_types]))
            .where(Event.start_naive >= start)
            .where(or_(Event.end_naive <= end, Event.end_naive is None))
        )
        count = cast(int, (await db.execute(count_query)).scalar())
        _LOGGER.debug("Found %s events", count)

        sem = asyncio.Semaphore(ctx.max_download)
        pb: ProgressBar[None] = typer.progressbar([], label="Downloading Events", length=count)
        pb.render_progress()

        query = (
            select(Event)
            .where(Event.event_type.in_([e.value for e in event_types]))
            .where(Event.start_naive >= start)
            .where(or_(Event.end_naive <= end, Event.end_naive is None))
        )
        result = await db.execute(query)
        smart_types_set = {s.value for s in smart_types}
        loop = asyncio.get_running_loop()
        for event in result.unique().scalars():
            event = cast(Event, event)
            if event.event_type == d.EventType.SMART_DETECT:
                if not event.smart_types.intersection(smart_types_set):
                    continue

            # wait for a free download slot
            await sem.acquire()
            sem.release()
            loop.create_task(_download_event(ctx, event, force, pb, sem))

        while pb.pos < count:
            await asyncio.sleep(1)
        pb.render_finish()

    return downloaded


async def _events(
    ctx: BackupContext,
    event_types: list[d.EventType],
    smart_types: list[d.SmartDetectObjectType],
    prune: bool,
    force: bool,
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
        _LOGGER.warning("Downloaded %s event(s)", await _download_events(ctx, event_types, smart_types, force))
    finally:
        _LOGGER.debug("Cleaning up Protect connection/database...")
        await ctx.protect.close_session()
        await ctx.db_engine.dispose()


@app.command(name="events")
def events_cmd(
    ctx: typer.Context,
    event_types: list[EventTypeChoice] = OPTION_EVENT_TYPES,
    smart_types: list[d.SmartDetectObjectType] = OPTION_SMART_TYPES,
    prune: bool = typer.Option(False, "-p", "--prune", help="Prune events older then start"),
    force: bool = typer.Option(False, "-f", "--force", help="Force update all events and redownload all clips"),
    no_input: bool = typer.Option(False, "--no-input"),
) -> None:
    """Backup thumbnails and video clips for camera events."""

    ufp_events = [d.EventType(e.value) for e in event_types]
    if prune and force:
        _wipe_files(ctx.obj, no_input)
    asyncio.run(_events(ctx.obj, ufp_events, smart_types, prune, force, no_input))
