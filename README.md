# Unofficial UniFi Protect Python API and CLI

[![Latest PyPI version](https://img.shields.io/pypi/v/pyunifiprotect)](https://pypi.org/project/pyunifiprotect/) [![Supported Python](https://img.shields.io/pypi/pyversions/pyunifiprotect)](https://pypi.org/project/pyunifiprotect/) [![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) [![CI](https://github.com/AngellusMortis/pyunifiprotect/actions/workflows/ci.yaml/badge.svg)](https://github.com/AngellusMortis/pyunifiprotect/actions/workflows/ci.yaml) [![Documentation](https://github.com/AngellusMortis/pyunifiprotect/actions/workflows/pages/pages-build-deployment/badge.svg)](https://angellusmortis.github.io/pyunifiprotect/)

`pyunifiprotect` is an unofficial API for UniFi Protect. There is no affiliation with Ubiquiti.

This module communicates with UniFi Protect surveillance software installed on a UniFi OS Console such as a Ubiquiti CloudKey+ or UniFi Dream Machine Pro.

The API is not documented by Ubiquiti, so there might be misses and/or frequent changes in this module, as Ubiquiti evolves the software.

The module is primarily written for the purpose of being used in Home Assistant core [integration for UniFi Protect](https://www.home-assistant.io/integrations/unifiprotect) but might be used for other purposes also.

## Smart Detections now Require Remote Access to enable

Smart Detections (person, vehicle, animal, face), a feature that previously could be used with local only console, [now requires you to enable remote access to enable](https://community.ui.com/questions/Cannot-enable-Smart-Detections/e3d50641-5c00-4607-9723-453cda557e35#answer/1d146426-89aa-4022-a0ae-fd5000846028).

Enabling Remote Access may grant other users access to your console [due to the fact Ubiquiti can reconfigure access controls at any time](https://community.ui.com/questions/Bug-Fix-Cloud-Access-Misconfiguration/fe8d4479-e187-4471-bf95-b2799183ceb7).

If you are not okay with the feature being locked behind Remote Access access, [let Ubiquiti know](https://community.ui.com/questions/Cannot-enable-Smart-Detections/e3d50641-5c00-4607-9723-453cda557e35).

## Documentation

[Full documentation for the project](https://angellusmortis.github.io/pyunifiprotect/).

## Requirements

If you want to install `pyunifiprotect` natively, the below are the requirements:

* [UniFi Protect](https://ui.com/camera-security) version 1.20+
    * Latest version of library is generally only tested against the two latest minor version. This is either two latest stable versions (such as 1.21.x and 2.0.x) or the latest EA version and stable version (such as 2.2.x EA and 2.1.x).
* [Python](https://www.python.org/) 3.9+
* POSIX compatible system
    * Library is only test on Linux, specifically the latest Debian version available for the official Python Docker images, but there is no reason the library should not work on any Linux distro or MacOS.
* [ffmpeg](https://ffmpeg.org/)
    * ffmpeg is primarily only for streaming audio to Protect cameras, this can be considered a soft requirement

Alternatively you can use the [provided Docker container](#using-docker-container), in which case the only requirement is [Docker](https://docs.docker.com/desktop/) or another OCI compatible orchestrator (such as Kubernetes or podman).

Windows is **not supported**. If you need to use `pyunifiprotect` on Windows, use Docker Desktop and the provided docker container or [WSL](https://docs.microsoft.com/en-us/windows/wsl/install).

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
* For more details on `TZ` and other environment variables, check the [command line docs](https://angellusmortis.github.io/pyunifiprotect/latest/cli/)

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

Generally any feature missing from the library is planned to be done eventually / nice to have with the following exceptions

### UniFi OS Features

Anything that is strictly a UniFi OS feature. If it ever done, it will be in a separate library that interacts with this one. Examples include:

* Managing RAID and disks
* Creating and managing users

### Remote Access / Ubiquiti Cloud Features

Anything that requires a Ubiquiti Account or "Remote Access" to be enabled is never going to be implemented by me
([@AngellusMortis](https://github.com/AngellusMortis/)) as I support UniFi Protect as a 100% local only product. PRs are welcome to implement any related
features though.

Examples include:

* Stream sharing
* Facial recognition

## Credits

* Bjarne Riis ([@briis](https://github.com/briis/)) for the original pyunifiprotect package
