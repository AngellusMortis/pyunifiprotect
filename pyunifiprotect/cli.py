import asyncio
import base64
import json
import logging
from pathlib import Path
import sys
from typing import Any, Optional, Union

import typer

from pyunifiprotect.api import ProtectApiClient
from pyunifiprotect.data import WSPacket
from pyunifiprotect.test_util import SampleDataGenerator
from pyunifiprotect.unifi_protect_server import UpvServer

_LOGGER = logging.getLogger("pyunifiprotect")

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
OPTION_NEW = typer.Option(False, "--new-client", "-n", help="New Beta API Client")
OPTION_WS_FILE = typer.Option(None, "--file", "-f", help="Path or raw binary Websocket message")
ARG_WS_DATA = typer.Argument(None, help="base64 encoded Websocket message")


app = typer.Typer()


def _call_unifi(protect: Union[UpvServer, ProtectApiClient], method: str, *args: Any, repeat: int = 1) -> None:
    async def callback() -> None:
        for _ in range(repeat):
            res = await getattr(protect, method)(*args)
            typer.echo(json.dumps(res, indent=2))

            if repeat > 1:
                await asyncio.sleep(2)

        # Close the Session
        await protect.close_session()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(callback())


def _listen_to_ws(protect: UpvServer) -> None:
    async def callback() -> None:
        await protect.ensure_authenticated()
        await protect.update()

        typer.echo("Listening websocket...")
        unsub = protect.subscribe_websocket(lambda u: typer.echo(f"Subscription: updated={u}"))

        for _ in range(15000):
            await asyncio.sleep(1)

        # Close the Session
        await protect.async_disconnect_ws()
        await protect.close_session()
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
) -> None:
    protect = UpvServer(None, address, port, username, password, verify_ssl=verify)
    _call_unifi(protect, "update", True)


@app.command()
def raw_data(
    username: str = OPTION_USERNAME,
    password: str = OPTION_PASSWORD,
    address: str = OPTION_ADDRESS,
    port: int = OPTION_PORT,
    verify: bool = OPTION_VERIFY,
) -> None:
    protect = UpvServer(None, address, port, username, password, verify_ssl=verify)
    _call_unifi(protect, "get_raw_device_info")


@app.command()
def event_data(
    username: str = OPTION_USERNAME,
    password: str = OPTION_PASSWORD,
    address: str = OPTION_ADDRESS,
    port: int = OPTION_PORT,
    verify: bool = OPTION_VERIFY,
    seconds: int = OPTION_SECONDS,
) -> None:
    protect = UpvServer(None, address, port, username, password, verify_ssl=verify)
    _call_unifi(protect, "get_raw_events", 10, repeat=seconds)


@app.command()
def websocket_data(
    username: str = OPTION_USERNAME,
    password: str = OPTION_PASSWORD,
    address: str = OPTION_ADDRESS,
    port: int = OPTION_PORT,
    verify: bool = OPTION_VERIFY,
) -> None:
    protect = UpvServer(None, address, port, username, password, verify_ssl=verify)
    _listen_to_ws(protect)


@app.command()
def shell(
    username: str = OPTION_USERNAME,
    password: str = OPTION_PASSWORD,
    address: str = OPTION_ADDRESS,
    port: int = OPTION_PORT,
    verify: bool = OPTION_VERIFY,
    new: bool = OPTION_NEW,
) -> None:
    if embed is None or colored is None:
        typer.echo("ipython and termcolor required for shell subcommand")
        sys.exit(1)

    if new:
        protect: Union[UpvServer, ProtectApiClient] = ProtectApiClient(
            address, port, username, password, verify_ssl=verify
        )
    else:
        protect = UpvServer(None, address, port, username, password, verify_ssl=verify)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(protect.update(True))

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    _LOGGER.setLevel(logging.DEBUG)
    _LOGGER.addHandler(console_handler)

    klass = "UpvServer"
    if new:
        klass = "ProtectApiClient"

    c = get_config()
    c.InteractiveShellEmbed.colors = "Linux"
    embed(header=colored(f"protect = {klass}(*args)", "green"), config=c, using="asyncio")


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
) -> None:
    if output_folder is None:
        tests_folder = Path(__file__).parent.parent / "tests"

        if not tests_folder.exists():
            typer.secho("Output folder required when not in dev-mode", fg="red")
            sys.exit(1)
        output_folder = (tests_folder / "sample_data").absolute()

    protect = ProtectApiClient(address, port, username, password, verify_ssl=verify, debug=True)
    SampleDataGenerator(protect, output_folder, anonymize, wait_type).generate()


@app.command()
def decode_ws_msg(ws_file: typer.FileBinaryRead = OPTION_WS_FILE, ws_data: Optional[str] = ARG_WS_DATA) -> None:
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
