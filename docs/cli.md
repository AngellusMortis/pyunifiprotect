---
hide:
- navigation
---
# Command Line

The `unifi-protect` command is provided to give a CLI interface to interact with your UniFi Protect instance as well. All
commands support JSON output so it works great with `jq` for complex scripting.

## Authentication

Following traditional [twelve factor app design](https://12factor.net/), the preferred way to provided authentication
credentials to provided environment variables, but CLI args are also supported.

!!! warning "About Ubiquiti SSO accounts"
    Ubiquiti SSO accounts are not supported and actively discouraged from being used. There is no option to use MFA. You are expected to use local access user. `pyunifiprotect` is not designed to allow you to use your owner account to access the your console or to be used over the public Internet as both pose a security risk.

### Environment Variables

```bash
export UFP_USERNAME=YOUR_USERNAME_HERE
export UFP_PASSWORD=YOUR_PASSWORD_HERE
export UFP_ADDRESS=YOUR_IP_ADDRESS
export UFP_PORT=443
# change to false if you do not have a valid HTTPS Certificate for your instance
export UFP_SSL_VERIFY=True

unifi-protect nvr
```

### CLI Args

```bash
unifi-protect -U YOUR_USERNAME_HERE -P YOUR_PASSWORD_HERE -a YOUR_IP_ADDRESS -p 443 --no-verify nvr
```

## Timezones

A number of commands allow you to enter a datetime as an argument or output files with the datetime in the filename. As a result, it is very important for `pyunifiprotect` to know your consoles local timezone. If you on a physical machine (not docker/VM), chances are this is already set up correctly for you (`/etc/localtime`), but otherwise you may need to set the `TZ` environment variable. `TZ` can also be used to override your system timezone as well if for whatever reason you need to. It should be the [Olson timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) for the timezone that your UniFi Protect Instance is in.

```bash
TZ=America/New_York unifi-protect --help
```

## Reference

```bash
$ unifi-protect --help
Usage: unifi-protect [OPTIONS] COMMAND [ARGS]...

UniFi Protect CLI
```

### Options

|      | Option                | Required?          | Env              | Type           | Default | Description                              |
| ---  | --------------------- | ------------------ | ---------------- | -------------- | ------- | ---------------------------------------- |
| `-U` | `--username`          | :white_check_mark: | `UFP_USERNAME`   | text           |         | UniFi Protect username                   |
| `-P` | `--password`          | :white_check_mark: | `UFP_PASSWORD`   | text           |         | UniFi Protect password                   |
| `-a` | `--address`           | :white_check_mark: | `UFP_ADDRESS`    | text           |         | UniFi Protect IP address or hostname     |
| `-p` | `--port`              |                    | `UFP_PORT`       | integer        | `443`   | UniFi Protect port                       |
|      | `--no-verify`         |                    | `UFP_SSL_VERIFY` | boolean        | `True`  | Verify SSL                               |
|      | `--output-format`     |                    |                  | `json`,`plain` | `plain` | Preferred output format. Not all commands support both JSON and plain and may still output in one or the other.
| `-u` | `--include-unadopted` |                    |                  |                |         | Include devices not adopted by this NVR. |
|      | `--show-completion`   |                    |                  |                |         | Show completion for the current shell, to copy it or customize the installation. |
|      | `--help`              |                    |                  |                |         | Show help message and exit.              |

### Subcommands

For any subcommand you can use `unifi-protect COMMAND --help`

| Command                | Description          |
| ---------------------- | -------------------- |
| `backup`               | [Backup CLI](#backup-cli).          |
| `cameras`              | Camera device CLI.   |
| `chimes`               | Chime device CLI.    |
| `decode-ws-msg`        | Decodes a base64 encoded UniFi Protect Websocket binary message. |
| `doorlocks`            | Doorlock device CLI. |
| `events`               | Events CLI.          |
| `generate-sample-data` | Generates sample data for UniFi Protect instance. |
| `lights`               | Lights device CLI.   |
| `liveviews`            | Liveviews CLI.       |
| `nvr`                  | NVR device CLI.      |
| `profile-ws`           | Profiles Websocket messages for UniFi Protect instance. |
| `sensors`              | Sensors device CLI.  |
| `shell`                | Opens iPython shell with Protect client initialized. |
| `viewers`              | Viewers device CLI.  |

#### Multiple Item CLI Commands

All adoptable device CLIs, event and liveview CLI work on the idea you have multiple cameras, multiple lights, multiple events or multiple liveviews. As such, they have four variations:

```bash
# list all devices (or events/liveviews)
unifi-protect cameras

# list short list of all devices (or events/liveviews)
unifi-protect cameras list-ids

# list a specific device (or event/liveview)
unifi-protect cameras DEVICE_ID

# run a command against a specific device (or event/liveview)
unifi-protect cameras DEVICE_ID COMMAND
```

!!! note
    The "list all devices" and "list a specific device" commands always return raw JSON. These commands can be paired with [jq](https://stedolan.github.io/jq/) to parse and quick extra device data from them.

| Command    | Description          |
| ---------- | -------------------- |
| `list-ids` | Requires no device ID. Prints list of "id name" for each device. |

##### Examples

###### List All Cameras

=== "Plain"

    ```bash
    $ unifi-protect cameras list-ids

    61b3f5c7033ea703e7000424: G4 Bullet
    61f9824e004adc03e700132c: G4 PTZ
    61be1d2f004bda03e700ab12: G4 Dome
    ```

=== "JSON"

    ```bash
    $ unifi-protect --output-format json cameras list-ids

    [
      [
        "61b3f5c7033ea703e7000424",
        "G4 Bullet"
      ],
      [
        "61f9824e004adc03e700132c",
        "G4 PTZ"
      ],
      [
        "61be1d2f004bda03e700ab12",
        "G4 Done"
      ],
      ...
    ]
    ```


###### Check if a Light is Online

```bash
$ unifi-protect cameras 61ddb66b018e2703e7008c19 | jq .isConnected
true
```

###### Take Snapshot of Camera

```bash
$ unifi-protect cameras 61ddb66b018e2703e7008c19 save-snapshot output.jpg
```

#### Adoptable Devices CLI Commands

Adoptable devices (Cameras, Chimes, Doorlocks, Lights, Sensors, Viewers) all have some commands in common.

| Command        | Description                                       |
| -----------    | ------------------------------------------------- |
| `adopt`        | Adopts a device.                                  |
| `bridge`       | Returns bridge device if connected via Bluetooth. |
| `is-bluetooth` | Returns if the device has Bluetooth or not.       |
| `is-wifi`      | Returns if the device has WiFi or not.            |
| `is-wired`     | Returns if the device is wired or not.            |
| `protect-url`  | Gets UniFi Protect management URL.                |
| `reboot`       | Reboots the device.                               |
| `unadopt`      | Unadopt/Unmanage adopted device.                  |
| `update`       | Updates the device.                               |

#### Backup CLI

```bash
$ unifi-protect backup --help

 Usage: unifi-protect backup [OPTIONS] COMMAND [ARGS]...

 Backup CLI.
 The backup CLI is still very WIP in progress and consider experimental and potentially unstable (interface may change in the future).
```

##### Backup Options

|      | Option            | Env                 | Type           | Default  | Description                                                          |
| ---  | ----------------- | ------------------- | -------------- | -------- | -------------------------------------------------------------------- |
| `-s` | `--start`         | `UFP_BACKUP_START`  | datetime       |          | Cutoff for start of backup. Defaults to start of recording for NVR.  |
| `-e` | `--end`           | `UFP_BACKUP_END`    | datetime       |          | Cutoff for end of backup. Defaults to now.                           |
|      | `--output-folder` | `UFP_BACKUP_OUTPUT` | path           | `$PWD`   | Base dir for creating files. Defaults to $PWD.                       |
|      | `--thumb-format`  |                     | text           | `{year}/{month}/{day}/{hour}/{datetime}{sep}{mac}{sep}{camera_slug}{event_type}{sep}thumb.jpg`    | Filename format to save event thumbnails to. Set to empty string ("") to skip saving event thumbnails. |
|      | `--gif-format`    |                     | text           | `{year}/{month}/{day}/{hour}/{datetime}{sep}{mac}{sep}{camera_slug}{event_type}{sep}animated.gif]`   | Filename format to save event gifs to. Set to empty string ("") to skip saving event gif. |
|      | `--event-format`  |                     | text           | `{year}/{month}/{day}/{hour}/{datetime}{sep}{mac}{sep}{camera_slug}{event_type}.mp4`   | Filename format to save event gifs to. Set to empty string ("") to skip saving event videos. |
|      | `--title-format`  |                     | text           | `{time_sort_pretty_local} {sep} {camera_name} {sep} {event_type_pretty} {sep} {length_pretty}`   | Format to use to tag title for video metadata. |
| `-v` | `--verbose`       |                     | boolean        | `False` | Debug logging.                                                        |
| `-d` | `--max-download`  |                     | integer        | `5`     | Max number of concurrent downloads. Adds additional loads to NVR.     |
|      | `--page-size`     |                     | integer        | `1000`  | Number of events fetched at once from local database. Increases memory usage. |
|      | `--length-cutoff` |                     | integer        | `3600`  | Event size cutoff for detecting abnormal events (in seconds).         |
|      | `--sep`           |                     | boolean        | `-`     | Separator used for formatting.                                        |
|      | `--help`          |                     |                |         | Show help message and exit.                                           |

##### File Name and Title Formatting

There are [5 options](#backup-options) controlling output format for file names and metadata. This allows you to customize backups to your liking. All 5 options are a template string. Here are all of the available templating variables:

| Variable                 | Description                                                                                  |
| ------------------------ | -------------------------------------------------------------------------------------------- |
| `year`                   | UTC year of start of export.                                                                 |
| `month`                  | UTC month of start of export.                                                                |
| `day`                    | UTC day of start of export.                                                                  |
| `hour`                   | UTC hour of start of export.                                                                 |
| `minute`                 | UTC minute of start of export.                                                               |
| `datetime`               | [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) formatted UTC datetime of start of export. Uses `sep` between parts. |
| `date`                   | [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) formatted UTC date of start of export. Uses `sep` between parts. |
| `time`                   | UTC time of start of export. Uses `sep` between parts. 24 hour time.                         |
| `time_sort_pretty`       | UTC time of start of export. Uses `:` between parts. 24 hour time.                           |
| `time_pretty`            | UTC time of start of export. Uses `:` between parts. 12 hour time with AM/PM.                |
| `year_local`             | [Local](#timezones) year of start of export.                                                  |
| `month_local`            | [Local](#timezones) month of start of export.                                                 |
| `day_local`              | [Local](#timezones) day of start of export.                                                   |
| `hour_local`             | [Local](#timezones) hour of start of export.                                                  |
| `minute_local`           | [Local](#timezones) minute of start of export.                                                |
| `datetime_local`         | [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) formatted [Local](#timezone) datetime of start of export. Uses `sep` between parts. |
| `date_local`             | [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) formatted [Local](#timezone) date of start of export. Uses `sep` between parts. |
| `time_local`             | [Local](#timezones) time of start of export. Uses `sep` between parts. 24 hour time.          |
| `time_sort_pretty_local` | [Local](#timezones) time of start of export. Uses `:` between parts. 24 hour time.            |
| `time_pretty_local`      | [Local](#timezones) time of start of export. Uses `:` between parts. 12 hour time with AM/PM. |
| `mac`                    | MAC address of camera.                                                                       |
| `camera_name`            | Name of camera.                                                                              |
| `camera_slug`            | Lowercased name of camera with spaces replaced with `sep`.                                   |
| `event_type`             | Lowercased name of the event exported.                                                       |
| `event_type_pretty`      | More human readable name of event exported.                                                  |
| `length_pretty`          | Human readable version of the length of the clip exported.                                   |
| `sep`                    | Separator to use in many cases.                                                              |

###### Datetimes

All datetimes for the Backup CLi can either be in [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) format or can be a human readable format that the Python library [dateparse](https://github.com/scrapinghub/dateparser) can understand. This will allow relative datetimes to be passed, such as `"1 hour ago"` which will make backing up incremental for cron jobs.

###### Formatting for Plex

You are able to export your Camera events and then access them in [Plex](https://www.plex.tv/) relatively well. For setup in Plex, the following is recommended:

* Enable the "Local Media Assets" Agent Source for the Movies Library Type (Settings -> Agents -> Movies). [Plex docs](https://support.plex.tv/articles/200265246-personal-media-movies/).
* Create a "Other Videos" library pointing to the same folder as your [--output-folder](#backup-options) folder.
    * Scanner: "Plex Video Files Scanner"
    * Agent: "Personal Media"

Recommended formats for the backup command:

| Option           | Format                                                            |
| ---------------- | ----------------------------------------------------------------- |
| `--thumb-format` | `{year_local}/{month_local}/{day_local}/{hour_local}/{title}.jpg` |
| `--gif-format`   | `{year_local}/{month_local}/{day_local}/{hour_local}/{title}.gif` |
| `--event-format` | `{year_local}/{month_local}/{day_local}/{hour_local}/{title}.mp4` |
| `--title-format` | `default` or whatever you want the title to be in Plex.           |

##### Backing Up Camera Events

```bash
$ unifi-protect backup events --help

 Usage: unifi-protect backup events [OPTIONS]

 Backup thumbnails and video clips for camera events.
```

|      | Option         | Type    | Default  | Description                                                |
| ---  | ---------------| --------| -------- | ---------------------------------------------------------- |
| `-t` | `--event-type` | `motion`, `ring`, `smartDetectZone` | `motion`, `ring`, `smartDetectZone` | Events to export. Can be used multiple time. |
| `-m` | `--smart-type` | `person`, `vehicle`, `package` | `person`, `vehicle`, `package` | Smart Detection types to export. Can be used multiple time. |
| `-p` | `--prune`      | boolean | `False`  | Prune events older then start.                             |
| `-f` | `--force`      | boolean | `False`  | Force update all events and redownload all clips.          |
| `-v` | `--verify`     | boolean | `False`  | Verifies files on disk.                                    |
|      | `--no-input`   | boolean | `False`  | Disables confirmation prompt if `-p` and `-f` both passed. |
|      | `--help`          |                |          | Show help message and exit.                      |

The `backup events` command essentially mirrors all of the selected events from your UniFi Protect instance into a local sqlite database (`events.db` inside of the `--output-folder`). As a result, the initial run make take a _really long time_ to run if your UniFi Protect instance has a lot of events inside of it.

As an example using a UniFi Protect instance with ~200k events and ~8 months of camera footage:

* Building the database is in the range of hours
* Doing the initial download of event thumbnails, gifs and video clips is in the range of tens of hours (potentially 1-2 days)
* Incremental or targeted backups are much faster (<1 per event)

!!! note "Cron Usage"

    For incremental backups in crons, it is recommended you run the command with an absolute start first to build your events database and do an initial download of files. This will significantly speed up the incremental backup commands.

##### Examples

###### Backup All Events

```bash
unifi-protect backup events
```

###### Backup All Smart Detections for the Past Hour

```bash
unifi-protect backup --start "1 hour ago" events -t smartDetectZone
```

###### Backup All Person Smart Detections from December 31st at 10PM to January 1st at 5AM

```bash
unifi-protect backup --start "2021-12-31T22:00:00" --end "2022-1-1T05:00:00" events -t smartDetectZone -m person
```

#### Camera CLI

Inherits [Multiple Item CLI Commands](#multiple-item-cli-commands) and [Adoptable Devices CLI Commands](#adoptable-devices-cli-commands).

##### Examples

###### Take Snapshot of Camera

```bash
$ unifi-protect cameras 61ddb66b018e2703e7008c19 save-snapshot output.jpg
```

###### Export Video From Camera

```bash
$ unifi-protect cameras 61ddb66b018e2703e7008c19 save-video export.mp4 2022-6-1T00:00:00 2022-6-1T00:00:30
```

!!! note "Timezones"

    See the section on [Timezones](#timezone) for determined what timezone your datetimes are in.

###### Play Audio File to Cameras Speaker

```bash
$ unifi-protect cameras 61ddb66b018e2703e7008c19 play-audio test.mp3
```

###### Include Unadopted Cameras in list

```bash
$ unifi-protect -u cameras list-ids
```

###### Adopt an Unadopted Camera

```bash
$ unifi-protect -u cameras 61ddb66b018e2703e7008c19 adopt
```

###### Enable SSH on Camera

```bash
$ unifi-protect cameras 61ddb66b018e2703e7008c19 set-ssh true

# get current value to verify
$ unifi-protect cameras 61ddb66b018e2703e7008c19 | jq .isSshEnabled
true
```

###### Reboot Camera

```bash
$ unifi-protect lights 61b3f5c801f8a703e7000428 reboot
```

###### Reboot All Cameras

```bash
for id in $(unifi-protect cameras list-ids | awk '{ print $1 }'); do
    unifi-protect cameras $id reboot
done
```
