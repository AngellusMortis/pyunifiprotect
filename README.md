# Python Wrapper for Unifi Protect API

[![Latest PyPI version](https://img.shields.io/pypi/v/pyunifiprotect)](https://pypi.org/project/pyunifiprotect/) [![Supported Python](https://img.shields.io/pypi/pyversions/pyunifiprotect)](https://pypi.org/project/pyunifiprotect/) [![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black) [![CI](https://github.com/briis/pyunifiprotect/actions/workflows/ci.yaml/badge.svg)](https://github.com/briis/pyunifiprotect/actions/workflows/ci.yaml)


This module communicates with Unifi Protect Surveillance software installed on a UnifiOS Console such as a Ubiquiti CloudKey+ or Unifi Dream Machine Pro

The API is not documented by Ubiquiti, so there might be misses and/or frequent changes in this module, as Ubiquiti evolves the software.

The module is primarily written for the purpose of being used in Home Assistant for the Custom Integration called `unifiprotect` but might be used for other purposes also.

Requires Unifi Protect version 1.20 or higher and Python 3.8+.

## Install

`pyunifiprotect` is avaible on PyPi:

```bash
pip install pyunifiprotect
```

## Usage

Unifi Protect itself is 100% async, so as such this library is primarily designed to be used in an async context.

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

All of the tests in the project are ran against that is generated from a real Unifi Protect instance and then anonymized so it is safe to commit to a Git repo. To generate new sample test data:

```
unifi-protect generate-sample-data
```

This will gather test data for 30 seconds and write it all into the `tests/sample_data` directory. During this time, it is a good idea to generate some good events that can tested. An example would be to generate a motion event for a FloodLight, Camera and/or Doorbell and then also ring a Doorbell.

### Linting and Testing

To lint code your code to verify all of the linters pass:

```
tox -e lint
```

To test your code to verify all the tests pass:

```
pytest
```

### Updating Requirements

To generate an updated pinned requirements file to be used for testing and CI:

```
pip-compile --upgrade --extra=shell --output-file=requirements_all.txt setup.cfg
pip-compile --upgrade --extra=dev --output-file=requirements_test.txt --pip-args='-c requirements_all.txt' setup.cfg
```

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
