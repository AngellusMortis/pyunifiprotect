# Unofficial UniFi Protect Python API and CLI

[![Latest PyPI version](https://img.shields.io/pypi/v/pyunifiprotect)](https://pypi.org/project/pyunifiprotect/) [![Supported Python](https://img.shields.io/pypi/pyversions/pyunifiprotect)](https://pypi.org/project/pyunifiprotect/) [![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) [![CI](https://github.com/briis/pyunifiprotect/actions/workflows/ci.yaml/badge.svg)](https://github.com/briis/pyunifiprotect/actions/workflows/ci.yaml)


This module communicates with UniFi Protect Surveillance software installed on a UniFi OS Console such as a Ubiquiti CloudKey+ or UniFi Dream Machine Pro.

The API is not documented by Ubiquiti, so there might be misses and/or frequent changes in this module, as Ubiquiti evolves the software.

The module is primarily written for the purpose of being used in Home Assistant core [integration for UniFi Protect](https://www.home-assistant.io/integrations/unifiprotect) but might be used for other purposes also.

Requires UniFi Protect version 1.20 or higher and Python 3.9+.

## Install

`pyunifiprotect` is avaible on PyPi:

```bash
pip install pyunifiprotect
```

## CLI Usage

The `unifi-protect` command is provided to give a CLI interface to interact with your UniFi Protect instance as well. All
commands support JSON output so it works great with `jq` for complex scripting.

### Authentication

Following traditional [twelve factor app design](https://12factor.net/), the perfered way to provided authentication
credentials to provided environment variables, but CLI args are also supported.

Ubiquiti SSO accounts are not supported and actively discouraged from being used. There is no option to use MFA. You are expected to use local access user.

#### Environment Variables

```bash
export UFP_USERNAME=YOUR_USERNAME_HERE
export UFP_PASSWORD=YOUR_PASSWORD_HERE
export UFP_ADDRESS=YOUR_IP_ADDRESS
export UFP_PORT=443
# change to false if you do not have a valid HTTPS Certificate for your instance
export UFP_SSL_VERIFY=True

unifi-protect nvr
```

#### CLI Args

```bash
unifi-protect -U YOUR_USERNAME_HERE -P YOUR_PASSWORD_HERE -a YOUR_IP_ADDRESS -p 443 --no-verify nvr
```

#### Docker Container

A Docker container is also provided so you do not need to install/manage Python as well. You can add the following to your `.bashrc` or similar.

```bash
function unifi-protect() {
    docker run --rm -it \
      -e UFP_USERNAME=YOUR_USERNAME_HERE \
      -e UFP_PASSWORD=YOUR_PASSWORD_HERE \
      -e UFP_ADDRESS=YOUR_IP_ADDRESS \
      -e UFP_PORT=443 \
      -e UFP_SSL_VERIFY=True \
      -v $PWD:/data ghcr.io/briis/pyunifiprotect:latest "$@"
}
```

Some notes about the Docker version since it is running inside of a container:

* You can update at any time using the command `docker pull ghcr.io/briis/pyunifiprotect:latest`
* Your local current working directory (`$PWD`) will automatically be mounted to `/data` inside of the container. For commands that output files, this is the _only_ path you can write to and have the file persist.
* The container supports `linux/amd64` and `linux/arm64` natively. This means it will also work well on MacOS or Windows using Docker Desktop.

### Subcommands

The command line has a fully featured help, so the best way to discovery and learn all of the possible commands is to use `unifi-protect --help`

* `nvr` - Interact with your NVR console
* `events` - Interact various events for the NVR console (like motion/smart detection events)
* `liveviews` - Interact with liveviews
* `camera`, `chimes`, `doorlocks`, `lights`, `sensors`, `viewers` - Interact with specific devices on adopted by your UniFi protect instance
* `shell` - Interactive IPyton shell (requires `pyunifiprotect[shell]` extra to be installed) with `ProtectApiClient already initalized
* `decode-ws-msg` - Mostly for debug purposes to debug a base64 binary Websocket message from UniFi Protect
* `generate-sample-data` - Mostly for debug purposes to generate fake data for CI / testing. Can also be used to share the current state of your UniFi Protect instance.
* `profile-ws` - Mostly for debug purposes to profile the number of ignored/processed Websocket messages

#### Examples

#### List All Cameras

```bash
$ unifi-protect cameras list-ids

61b3f5c7033ea703e7000424: G4 Bullet
61f9824e004adc03e700132c: G4 PTZ
61be1d2f004bda03e700ab12: G4 Dome
```

#### Check if a Camera is Online

```bash
$ unifi-protect cameras 61ddb66b018e2703e7008c19 | jq .isConnected
true
```

#### Take Snapshot of Camera

```bash
$ unifi-protect cameras 61ddb66b018e2703e7008c19 save-snapshot output.jpg
```

#### Export Video From Camera

```bash
$ unifi-protect cameras 61ddb66b018e2703e7008c19 save-video export.mp4 2022-6-1T00:00:00 2022-6-1T00:00:30
```

Any field that takes a datetime field uses the timezone from your system locale by default. If this is not configured
correctly, it will automatically default to UTC. If you would like to override the timezone, you can use the `TZ`
environment variable.

For example, use `America/New_York` or US East timezone:

```bash
$ TZ="America/New_York" unifi-protect cameras 61ddb66b018e2703e7008c19 save-video  export.mp4 2022-6-1T00:00:00 2022-6-1T00:00:30
```

#### Play Audio File to Cameras Speaker

```bash
$ unifi-protect cameras 61ddb66b018e2703e7008c19 play-audio test.mp3
```

#### Include Unadopted Cameras in list

```bash
$ unifi-protect -u cameras list-ids
```

#### Adopt an Unadopted Camera

```bash
$ unifi-protect -u cameras 61ddb66b018e2703e7008c19 adopt
```

#### Enable SSH on Camera

```bash
$ unifi-protect cameras 61ddb66b018e2703e7008c19 set-ssh true

# get current value to verify
$ unifi-protect cameras 61ddb66b018e2703e7008c19 | jq .isSshEnabled
true
```

#### Reboot Flood Light

```bash
$ unifi-protect lights 61b3f5c801f8a703e7000428 reboot
```

#### Reboot All Cameras

```bash
for id in $(unifi-protect cameras list-ids | awk '{ print $1 }'); do
    unifi-protect cameras $id reboot
done
```

## Library Usage

UniFi Protect itself is 100% async, so as such this library is primarily designed to be used in an async context.

The main interface for the library is the `pyunifiprotect.ProtectApiClient`:

```python
from pyunifiprotect import ProtectApiClient

protect = ProtectApiClient(host, port, username, password, verify_ssl=True)

await protect.update() # this will initalize the protect .bootstrap and open a Websocket connection for updates

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

The following the noticble features are that still missing from pyunifiprotect. All of them are planned for "some day" / "nice to have" except where noted.

* Animated thumbnails for events
* Timelapse video exporting
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
* Any strictly UniFi OS feature like managing RAID, creating users, etc. -- Out of Scope. If it ever done, it will be in a seperate library that interacts with this one

## Development

### Setup

Development with this project is designed to be done via VS Code + Docker. It is a pretty standard Python package, so feel free to use anything else, but all documentation assumes you are using VS Code.

* [VS Code](https://code.visualstudio.com/) + [Remote Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
* [Docker](https://docs.docker.com/get-docker/)
    * If you are using Linux, you need Docker Engine 19.0 or newer and you need to enable [Docker Buildkit](https://docs.docker.com/develop/develop-images/build_enhancements/)
    * If you are using Docker Desktop on MacOS or Winows, you will need Docker Desktop 3.2.0 or newer

Once you have all three setup,

1. Clone repo
2. Open the main folder
3. You should be prompted to "Reopen folder to develop in a container". If you are not, you can open the [Command Palette](https://code.visualstudio.com/docs/getstarted/userinterface#_command-palette) run the "Remote-Containers: Reopen in Container" command.

This should be all you need to do to get a working development environment. The docker container will automatically be build and VS Code will attach itself to it. The integrated terminal in VS Code will already be set up with the `unifi-protect` command.

### Authenticating with your Local Protect Instance

The project allows you to create an environment file to put your local protect instance data into so you do not need to constantly enter in or accidentally commit it to the Git repo.

Make a file in the root of the project named `.env` with the following and change accordingly:

```
UFP_USERNAME=YOUR_USERNAME_HERE
UFP_PASSWORD=YOUR_PASSWORD_HERE
UFP_ADDRESS=YOUR_IP_ADDRESS
UFP_PORT=443
# change to false if you do not have a valid HTTPS Certificate for your instance
UFP_SSL_VERIFY=True
```

### Generating Test Data

All of the tests in the project are ran against that is generated from a real UniFi Protect instance and then anonymized so it is safe to commit to a Git repo. To generate new sample test data:

```
unifi-protect generate-sample-data
```

This will gather test data for 30 seconds and write it all into the `tests/sample_data` directory. During this time, it is a good idea to generate some good events that can tested. An example would be to generate a motion event for a FloodLight, Camera and/or Doorbell and then also ring a Doorbell.

### Linting and Testing

The following scripts exist to easily format, lint and test code in the same fashion as CI:

```
.bin/format-code
.bin/lint-code
.bin/test-code
```

### Updating Requirements

To generate an updated pinned requirements file to be used for testing and CI using the `.bin/update-requirements` script.

There is also a [VS Code task](https://code.visualstudio.com/Docs/editor/tasks) to run this as well.

#### VS Code Integration

Tests can also be ran directly from within VS Code using the testing side panel.

### Generating and Testing with Real Data

You can also generate and run tests against real non-anonymized data to help troubleshoot issues and see real results. You can also increase the gather time for events to give you more time to generate events for testing as well.

```
export UFP_SAMPLE_DIR=/workspaces/pyunifiprotect/test-data
unifi-protect generate-sample-data -w 300 --actual
```

You can then make `pytest` use this real data as well:

```
export UFP_SAMPLE_DIR=/workspaces/pyunifiprotect/test-data
pytest
```
