import asyncio
import json
import logging
import sys

from aiohttp import ClientSession, CookieJar
from traitlets.config import get_config
import typer

from .unifi_protect_server import _LOGGER, UpvServer

try:
    from IPython import embed
    from termcolor import colored
except ImportError:
    embed = termcolor = None

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
