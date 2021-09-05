import asyncio
import base64
import json
import logging
from pathlib import Path
import sys
from typing import Optional

from aiohttp import ClientSession, CookieJar
import typer

from .test_util import SampleDataGenerator
from .unifi_data import WSPacket
from .unifi_protect_server import _LOGGER, UpvServer

try:
    from IPython import embed  # type: ignore
    from termcolor import colored
    from traitlets.config import get_config  # type: ignore
except ImportError:
    embed = termcolor = get_config = None

OPTION_USERNAME = typer.Option(
    ...,
    "--username",
    "-U",
    help="Unifi Protect Username",
    prompt=True,
    envvar="UFP_USERNAME",
)
OPTION_PASSWORD = typer.Option(
    ...,
    "--password",
    "-P",
    help="Unifi Protect password",
    prompt=True,
    hide_input=True,
    envvar="UFP_PASSWORD",
)
OPTION_ADDRESS = typer.Option(
    ...,
    "--address",
    "-a",
    prompt=True,
    help="Unifi Protect IP address or hostname",
    envvar="UFP_ADDRESS",
)
OPTION_PORT = typer.Option(443, "--port", "-p", help="Unifi Protect Port", envvar="UFP_PORT")
OPTION_SECONDS = typer.Option(15, "--seconds", "-s", help="Seconds to pull events")
OPTION_VERIFY = typer.Option(True, "--verify", "-v", help="Verify SSL", envvar="UFP_SSL_VERIFY")
OPTION_ANON = typer.Option(True, "--actual", help="Do not anonymize test data")
OPTION_WAIT = typer.Option(30, "--wait", "-w", help="Time to wait for Websocket messages")
OPTION_OUTPUT = typer.Option(
    None,
    "--output",
    "-o",
    help="Output folder, defaults to `tests` folder one level above this file",
    envvar="UFP_SAMPLE_DIR",
)
OPTION_WS_FILE = typer.Option(None, "--file", "-f", help="Path or raw binary Websocket message")
ARG_WS_DATA = typer.Argument(None, help="base64 encoded Websocket message")


app = typer.Typer()


def _get_server(username, password, address, port, verify):
    session = ClientSession(cookie_jar=CookieJar(unsafe=True))

    # Log in to Unifi Protect
    protect = UpvServer(session, address, port, username, password, verify_ssl=verify)

    return protect


def _call_unifi(protect, method, *args, repeat=1):
    async def callback():
        for _ in range(repeat):
            res = await getattr(protect, method)(*args)
            typer.echo(json.dumps(res, indent=2))

            if repeat > 1:
                await asyncio.sleep(2)

        # Close the Session
        await protect.req.close()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(callback())


def _listen_to_ws(protect):
    async def callback():
        await protect.ensure_authenticated()
        await protect.update()

        typer.echo("Listening websocket...")
        unsub = protect.subscribe_websocket(lambda u: typer.echo(f"Subscription: updated={u}"))

        for _ in range(15000):
            await asyncio.sleep(1)

        # Close the Session
        await protect.req.close()
        await protect.async_disconnect_ws()
        unsub()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(callback())


@app.command()
def sensor(
    username: str = OPTION_USERNAME,
    password: str = OPTION_PASSWORD,
    address: str = OPTION_ADDRESS,
    port: int = OPTION_PORT,
    verify: bool = OPTION_VERIFY,
):
    protect = _get_server(username, password, address, port, verify)
    _call_unifi(protect, "update", True)


@app.command()
def raw_data(
    username: str = OPTION_USERNAME,
    password: str = OPTION_PASSWORD,
    address: str = OPTION_ADDRESS,
    port: int = OPTION_PORT,
    verify: bool = OPTION_VERIFY,
):
    protect = _get_server(username, password, address, port, verify)
    _call_unifi(protect, "get_raw_device_info")


@app.command()
def event_data(
    username: str = OPTION_USERNAME,
    password: str = OPTION_PASSWORD,
    address: str = OPTION_ADDRESS,
    port: int = OPTION_PORT,
    verify: bool = OPTION_VERIFY,
    seconds: int = OPTION_SECONDS,
):
    protect = _get_server(username, password, address, port, verify)
    _call_unifi(protect, "get_raw_events", 10, repeat=seconds)


@app.command()
def websocket_data(
    username: str = OPTION_USERNAME,
    password: str = OPTION_PASSWORD,
    address: str = OPTION_ADDRESS,
    port: int = OPTION_PORT,
    verify: bool = OPTION_VERIFY,
):
    protect = _get_server(username, password, address, port, verify)
    _listen_to_ws(protect)


@app.command()
def shell(
    username: str = OPTION_USERNAME,
    password: str = OPTION_PASSWORD,
    address: str = OPTION_ADDRESS,
    port: int = OPTION_PORT,
    verify: bool = OPTION_VERIFY,
):
    if embed is None or colored is None:
        typer.echo("ipython and termcolor required for shell subcommand")
        sys.exit(1)

    protect = _get_server(username, password, address, port, verify)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(protect.update(True))

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    _LOGGER.setLevel(logging.DEBUG)
    _LOGGER.addHandler(console_handler)

    c = get_config()
    c.InteractiveShellEmbed.colors = "Linux"
    embed(header=colored("protect = UpvServer(*args)", "green"), config=c, using="asyncio")


@app.command()
def generate_sample_data(
    username: str = OPTION_USERNAME,
    password: str = OPTION_PASSWORD,
    address: str = OPTION_ADDRESS,
    port: int = OPTION_PORT,
    verify: bool = OPTION_VERIFY,
    anonymize: bool = OPTION_ANON,
    wait_type: int = OPTION_WAIT,
    output_folder: Optional[Path] = OPTION_OUTPUT,
):
    if output_folder is None:
        tests_folder = Path(__file__).parent.parent / "tests"

        if not tests_folder.exists():
            typer.secho("Output folder required when not in dev-mode", fg="red")
            sys.exit(1)
        output_folder = (tests_folder / "sample_data").absolute()

    protect = _get_server(username, password, address, port, verify)
    SampleDataGenerator(protect, output_folder, anonymize, wait_type).generate()


@app.command()
def decode_ws_msg(ws_file: typer.FileBinaryRead = OPTION_WS_FILE, ws_data=ARG_WS_DATA):
    if ws_file is None and ws_data is None:
        typer.secho("Websocket data required", fg="red")
        sys.exit(1)

    ws_data_raw = b""
    if ws_file is not None:
        ws_data_raw = ws_file.read()
    elif ws_data is not None:
        ws_data_raw = base64.b64decode(ws_data.encode("utf8"))

    packet = WSPacket(ws_data_raw)
    response = {"action": packet.action_frame.data, "data": packet.data_frame.data}

    typer.echo(json.dumps(response))
