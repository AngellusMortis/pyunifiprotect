# pylint: disable=protected-access

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from shlex import split
from subprocess import run
import time
from typing import Any, Dict, List, Optional, Tuple, Union, overload

from PIL import Image
import aiohttp
import typer

from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.data import EventType, WSJSONPacketFrame, WSPacket
from pyunifiprotect.test_util.anonymize import (
    anonymize_data,
    anonymize_prefixed_event_id,
)
from pyunifiprotect.unifi_data import process_camera
from pyunifiprotect.utils import from_js_time, is_online

SLEEP_INTERVAL = 2
BLANK_VIDEO_CMD = "ffmpeg -y -hide_banner -loglevel error -f lavfi -i color=size=1280x720:rate=25:color=black -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 -t {length} {filename}"


def placeholder_image(output_path: Path, width: int, height: Optional[int] = None) -> None:
    if height is None:
        height = width

    image = Image.new("RGB", (width, height), (128, 128, 128))
    image.save(output_path, "PNG")


class SampleDataGenerator:
    """Generate sample data for debugging and testing purposes"""

    _record_num_ws: int = 0
    _record_ws_start_time: float = time.monotonic()
    _record_listen_for_events: bool = False
    _record_ws_messages: Dict[str, Dict[str, Any]] = {}

    constants: Dict[str, Any] = {}
    client: ProtectApiClient
    output_folder: Path
    anonymize: bool
    wait_time: int

    def __init__(self, client: ProtectApiClient, output: Path, anonymize: bool, wait_time: int) -> None:
        self.client = client
        self.output_folder = output
        self.anonymize = anonymize
        self.wait_time = wait_time

    def generate(self) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.async_generate())

    async def async_generate(self, close_session: bool = True) -> None:
        typer.echo(f"Output folder: {self.output_folder}")
        self.output_folder.mkdir(parents=True, exist_ok=True)
        self.client.subscribe_raw_websocket(self._handle_ws_message)

        typer.echo("Updating devices...")
        await self.client.update(True)

        bootstrap: Dict[str, Any] = await self.client.api_request_obj("bootstrap")
        bootstrap = self.write_json_file("sample_bootstrap", bootstrap)
        self.constants["server_name"] = bootstrap["nvr"]["name"]
        self.constants["server_id"] = bootstrap["nvr"]["mac"]
        self.constants["server_version"] = bootstrap["nvr"]["version"]
        self.constants["server_ip"] = bootstrap["nvr"]["host"]
        self.constants["server_model"] = bootstrap["nvr"]["type"]
        self.constants["last_update_id"] = bootstrap["lastUpdateId"]
        self.constants["user_id"] = bootstrap["authUserId"]
        self.constants["counts"] = {
            "camera": len(bootstrap["cameras"]),
            "user": len(bootstrap["users"]),
            "group": len(bootstrap["groups"]),
            "liveview": len(bootstrap["liveviews"]),
            "viewer": len(bootstrap["viewers"]),
            "display": len(bootstrap["displays"]),
            "light": len(bootstrap["lights"]),
            "bridge": len(bootstrap["bridges"]),
            "sensor": len(bootstrap["sensors"]),
            "doorlock": len(bootstrap["doorlocks"]),
            "chime": len(bootstrap["chimes"]),
            "schedule": len(bootstrap["schedules"]),
        }

        await self.record_ws_events()
        motion_event, smart_detection = await self.generate_event_data()
        await self.generate_device_data(motion_event, smart_detection)

        if close_session:
            await self.client.close_session()

        self.write_json_file("sample_constants", self.constants, anonymize=False)

    async def record_ws_events(self) -> None:
        if self.wait_time <= 0:
            typer.echo("Skipping recording Websocket messages...")
            return

        self._record_num_ws = 0
        self._record_ws_start_time = time.monotonic()
        self._record_listen_for_events = True
        self._record_ws_messages = {}

        typer.echo(f"Waiting {self.wait_time} seconds for WS messages...")
        with typer.progressbar(range(self.wait_time // SLEEP_INTERVAL), label="Waiting for WS messages") as progress:
            for i in progress:
                if i > 0:
                    await asyncio.sleep(SLEEP_INTERVAL)

        self._record_listen_for_events = False
        await self.client.async_disconnect_ws()
        self.write_json_file("sample_ws_messages", self._record_ws_messages, anonymize=False)

    @overload
    def write_json_file(self, name: str, data: List[Any], anonymize: Optional[bool] = None) -> List[Any]:
        ...

    @overload
    def write_json_file(self, name: str, data: Dict[str, Any], anonymize: Optional[bool] = None) -> Dict[str, Any]:
        ...

    def write_json_file(
        self, name: str, data: Union[List[Any], Dict[str, Any]], anonymize: Optional[bool] = None
    ) -> Union[List[Any], Dict[str, Any]]:
        if anonymize is None:
            anonymize = self.anonymize

        if anonymize:
            data = anonymize_data(data)

        typer.echo(f"Writing {name}...")
        with open(self.output_folder / f"{name}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            f.write("\n")

        return data

    def write_binary_file(self, name: str, ext: str, raw: Optional[bytes]) -> None:
        if raw is None:
            typer.echo(f"No image data, skipping {name}...")
            return

        typer.echo(f"Writing {name}...")
        with open(self.output_folder / f"{name}.{ext}", "wb") as f:
            f.write(raw)

    def write_image_file(self, name: str, raw: Optional[bytes]) -> None:
        self.write_binary_file(name, "png", raw)

    async def generate_event_data(self) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        data = await self.client.get_events_raw()

        self.constants["time"] = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
        self.constants["event_count"] = len(data)

        motion_event: Optional[Dict[str, Any]] = None
        smart_detection: Optional[Dict[str, Any]] = None
        for event_dict in reversed(data):
            if (
                motion_event is None
                and event_dict["type"] == EventType.MOTION.value
                and event_dict["camera"] is not None
                and event_dict["thumbnail"] is not None
                and event_dict["heatmap"] is not None
                and event_dict["end"] is not None
            ):
                motion_event = deepcopy(event_dict)
                typer.echo(f"Using motion event: {motion_event['id']}...")
            elif (
                smart_detection is None
                and event_dict["type"] == EventType.SMART_DETECT.value
                and event_dict["camera"] is not None
                and event_dict["end"] is not None
            ):
                smart_detection = deepcopy(event_dict)
                typer.echo(f"Using smart detection event: {smart_detection['id']}...")

            if motion_event is not None and smart_detection is not None:
                break

        # anonymize data after pulling events
        data = self.write_json_file("sample_raw_events", data)

        return motion_event, smart_detection

    async def generate_device_data(
        self, motion_event: Optional[Dict[str, Any]], smart_detection: Optional[Dict[str, Any]]
    ) -> None:
        await asyncio.gather(
            self.generate_camera_data(),
            self.generate_motion_data(motion_event),
            self.generate_smart_detection_data(smart_detection),
            self.generate_light_data(),
            self.generate_viewport_data(),
            self.generate_sensor_data(),
            self.generate_bridge_data(),
            self.generate_liveview_data(),
        )

    async def generate_camera_data(self) -> None:
        objs = await self.client.api_request_list("cameras")
        device_id: Optional[str] = None
        camera_is_online = False
        for obj_dict in objs:
            device_id = obj_dict["id"]
            if is_online(obj_dict):
                camera_is_online = True
                break

        if device_id is None:
            typer.echo("No camera found. Skipping camera endpoints...")
            return

        # json data
        obj = await self.client.api_request_obj(f"cameras/{device_id}")
        self.write_json_file("sample_camera", deepcopy(obj))
        self.constants["camera_online"] = camera_is_online

        if not camera_is_online:
            typer.echo("Camera is not online, skipping snapshot, thumbnail and heatmap generation")

        # snapshot
        processd_camera = process_camera(None, self.client._host, deepcopy(obj), False)
        filename = "sample_camera_snapshot"
        if self.anonymize:
            typer.echo(f"Writing {filename}...")
            placeholder_image(
                self.output_folder / f"{filename}.png", processd_camera["image_width"], processd_camera["image_height"]
            )
        else:
            snapshot = await self.client.get_camera_snapshot(
                obj["id"], processd_camera["image_width"], processd_camera["image_height"]
            )
            self.write_image_file(filename, snapshot)

    async def generate_motion_data(self, motion_event: Optional[Dict[str, Any]]) -> None:
        if motion_event is None:
            typer.echo("No motion event, skipping thumbnail and heatmap generation...")
            return

        # event thumbnail
        filename = "sample_camera_thumbnail"
        thumbnail_id = motion_event["thumbnail"]
        if self.anonymize:
            typer.echo(f"Writing {filename}...")
            placeholder_image(self.output_folder / f"{filename}.png", 640, 360)
            thumbnail_id = anonymize_prefixed_event_id(thumbnail_id)
        else:
            img = await self.client.get_event_thumbnail(thumbnail_id)
            self.write_image_file(filename, img)
        self.constants["camera_thumbnail"] = thumbnail_id

        # event heatmap
        filename = "sample_camera_heatmap"
        heatmap_id = motion_event["heatmap"]
        if self.anonymize:
            typer.echo(f"Writing {filename}...")
            placeholder_image(self.output_folder / f"{filename}.png", 640, 360)
            heatmap_id = anonymize_prefixed_event_id(heatmap_id)
        else:
            img = await self.client.get_event_heatmap(heatmap_id)
            self.write_image_file(filename, img)
        self.constants["camera_heatmap"] = heatmap_id

        # event video
        filename = "sample_camera_video"
        length = int((motion_event["end"] - motion_event["start"]) / 1000)
        if self.anonymize:
            run(
                split(BLANK_VIDEO_CMD.format(length=length, filename=self.output_folder / f"{filename}.mp4")),
                check=True,
            )
        else:
            video = await self.client.get_camera_video(
                motion_event["camera"], from_js_time(motion_event["start"]), from_js_time(motion_event["end"]), 2
            )
            self.write_binary_file(filename, "mp4", video)
        self.constants["camera_video_length"] = length

    async def generate_smart_detection_data(self, smart_detection: Optional[Dict[str, Any]]) -> None:
        if smart_detection is None:
            typer.echo("No smart detection event, skipping smart detection data...")
            return

        data = await self.client.get_event_smart_detect_track_raw(smart_detection["id"])
        self.write_json_file("sample_event_smart_track", data)

    async def generate_light_data(self) -> None:
        objs = await self.client.api_request_list("lights")
        device_id: Optional[str] = None
        for obj_dict in objs:
            device_id = obj_dict["id"]
            if is_online(obj_dict):
                break

        if device_id is None:
            typer.echo("No light found. Skipping light endpoints...")
            return

        obj = await self.client.api_request_obj(f"lights/{device_id}")
        self.write_json_file("sample_light", obj)

    async def generate_viewport_data(self) -> None:
        objs = await self.client.api_request_list("viewers")
        device_id: Optional[str] = None
        for obj_dict in objs:
            device_id = obj_dict["id"]
            if is_online(obj_dict):
                break

        if device_id is None:
            typer.echo("No viewer found. Skipping viewer endpoints...")
            return

        obj = await self.client.api_request_obj(f"viewers/{device_id}")
        self.write_json_file("sample_viewport", obj)

    async def generate_sensor_data(self) -> None:
        objs = await self.client.api_request_list("sensors")
        device_id: Optional[str] = None
        for obj_dict in objs:
            device_id = obj_dict["id"]
            if is_online(obj_dict):
                break

        if device_id is None:
            typer.echo("No sensor found. Skipping sensor endpoints...")
            return

        obj = await self.client.api_request_obj(f"sensors/{device_id}")
        self.write_json_file("sample_sensor", obj)
        self.write_json_file("sample_sensors", objs)

    async def generate_bridge_data(self) -> None:
        objs = await self.client.api_request_list("bridges")
        device_id: Optional[str] = None
        for obj_dict in objs:
            device_id = obj_dict["id"]
            if is_online(obj_dict):
                break

        if device_id is None:
            typer.echo("No bridge found. Skipping bridge endpoints...")
            return

        obj = await self.client.api_request_obj(f"bridges/{device_id}")
        self.write_json_file("sample_bridge", obj)

    async def generate_liveview_data(self) -> None:
        objs = await self.client.api_request_list("liveviews")
        device_id: Optional[str] = None
        for obj_dict in objs:
            device_id = obj_dict["id"]
            break

        if device_id is None:
            typer.echo("No liveview found. Skipping liveview endpoints...")
            return

        obj = await self.client.api_request_obj(f"liveviews/{device_id}")
        self.write_json_file("sample_liveview", obj)

    def _handle_ws_message(self, msg: aiohttp.WSMessage) -> None:
        if not self._record_listen_for_events:
            return

        now = time.monotonic()
        self._record_num_ws += 1
        time_offset = now - self._record_ws_start_time

        if msg.type == aiohttp.WSMsgType.BINARY:
            packet = WSPacket(msg.data)

            if not isinstance(packet.action_frame, WSJSONPacketFrame):
                typer.secho(f"Got non-JSON action frame: {packet.action_frame.payload_format}", fg="yellow")
                return

            if not isinstance(packet.data_frame, WSJSONPacketFrame):
                typer.secho(f"Got non-JSON data frame: {packet.data_frame.payload_format}", fg="yellow")
                return

            if self.anonymize:
                packet.action_frame.data = anonymize_data(packet.action_frame.data)
                packet.data_frame.data = anonymize_data(packet.data_frame.data)
                packet.pack_frames()

            self._record_ws_messages[str(time_offset)] = {
                "raw": packet.raw_base64,
                "action": packet.action_frame.data,
                "data": packet.data_frame.data,
            }
        else:
            typer.secho(f"Got non-binary message: {msg.type}", fg="yellow")
