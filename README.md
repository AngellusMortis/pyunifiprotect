# Unofficial UniFi Protect Python API and CLI

[![Latest PyPI version](https://img.shields.io/pypi/v/pyunifiprotect)](https://pypi.org/project/pyunifiprotect/) [![Supported Python](https://img.shields.io/pypi/pyversions/pyunifiprotect)](https://pypi.org/project/pyunifiprotect/) [![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) [![CI](https://github.com/AngellusMortis/pyunifiprotect/actions/workflows/ci.yaml/badge.svg)](https://github.com/AngellusMortis/pyunifiprotect/actions/workflows/ci.yaml)

`pyunifiprotect` is an unofficial API for UniFi Protect. There is no affiliation with Ubiquiti.

This module communicates with UniFi Protect surveillance software installed on a UniFi OS Console such as a Ubiquiti CloudKey+ or UniFi Dream Machine Pro.

The API is not documented by Ubiquiti, so there might be misses and/or frequent changes in this module, as Ubiquiti evolves the software.

The module is primarily written for the purpose of being used in Home Assistant core [integration for UniFi Protect](https://www.home-assistant.io/integrations/unifiprotect) but might be used for other purposes also.

**Requires UniFi Protect version 1.20 or higher and Python 3.9+.**

## Install

### From PyPi

`pyunifiprotect` is available on PyPi:

```bash
pip install pyunifiprotect
```

### From Github

```bash
pip install git+https://github.com/AngellusMortis/pyunifiprotect.git#egg=pyunifiprotect
```

### Using Docker Container

A Docker container is also provided so you do not need to install/manage Python as well. You can add the following to your `.bashrc` or similar.

```bash
function unifi-protect() {
    docker run --rm -it \
      -e UFP_USERNAME=YOUR_USERNAME_HERE \
      -e UFP_PASSWORD=YOUR_PASSWORD_HERE \
      -e UFP_ADDRESS=YOUR_IP_ADDRESS \
      -e UFP_PORT=443 \
      -e UFP_SSL_VERIFY=True \
      -e TZ=America/New_York \
      -v $PWD:/data ghcr.io/angellusmortis/pyunifiprotect:latest "$@"
}
```

Some notes about the Docker version since it is running inside of a container:

* You can update at any time using the command `docker pull ghcr.io/AngellusMortis/pyunifiprotect:latest`
* Your local current working directory (`$PWD`) will automatically be mounted to `/data` inside of the container. For commands that output files, this is the _only_ path you can write to and have the file persist.
* The container supports `linux/amd64` and `linux/arm64` natively. This means it will also work well on MacOS or Windows using Docker Desktop.
* For versions of `pyunifiprotect` before v4.1.5, you need to use the `ghcr.io/briis/pyunifiprotect` image instead.
* `TZ` should be the [Olson timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) for the timezone your UniFi Protect instance is in.
* For more details on `TZ` and other environment variables, check the [command line docs](/cli/)

## Quickstart

### CLI

!!! warning "About Ubiquiti SSO accounts"
    Ubiquiti SSO accounts are not supported and actively discouraged from being used. There is no option to use MFA. You are expected to use local access user. `pyunifiprotect` is not designed to allow you to use your owner account to access the your console or to be used over the public Internet as both pose a security risk.

```bash
export UFP_USERNAME=YOUR_USERNAME_HERE
export UFP_PASSWORD=YOUR_PASSWORD_HERE
export UFP_ADDRESS=YOUR_IP_ADDRESS
export UFP_PORT=443
# change to false if you do not have a valid HTTPS Certificate for your instance
export UFP_SSL_VERIFY=True

unifi-protect --help
unifi-protect nvr
```

### Python

UniFi Protect itself is 100% async, so as such this library is primarily designed to be used in an async context.

The main interface for the library is the `pyunifiprotect.ProtectApiClient`:

```python
from pyunifiprotect import ProtectApiClient

protect = ProtectApiClient(host, port, username, password, verify_ssl=True)

await protect.update() # this will initialize the protect .bootstrap and open a Websocket connection for updates

# get names of your cameras
for camera in protect.bootstrap.cameras.values():
    print(camera.name)

# subscribe to Websocket for updates to UFP
def callback(msg: WSSubscriptionMessage):
    # do stuff

unsub = protect.subscribe_websocket(callback)

# remove subscription
unsub()

```

## TODO / Planned / Not Implemented

The following the noticeable features are that still missing from pyunifiprotect. All of them are planned for "some day" / "nice to have" except where noted.

* Liveview creating/updating/deleting
* PTZ controls
* Creating WebRTC streaming connections
* Backups
* Device Groups
* Record Scheduling
* Battery powered cameras (G3 Battery, Aplify Vision)
* Camera analytics and live heatmaps
* Reconfiguring WiFi
* "Locate" feature for Lights/Sensors/Doorlocks
* The `/timeline` API endpoint
* User/Group/Permission management -- partially implemented as users and groups are modeled, just not fleshed out
* Any strictly UniFi OS feature like managing RAID, creating users, etc. -- Out of Scope. If it ever done, it will be in a separate library that interacts with this one

## Credits

* Bjarne Riis ([@briis](https://github.com/briis/)) for the original pyunifiprotect package
