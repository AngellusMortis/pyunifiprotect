# Generating Sample Data to help with Testing/Features

## Setup Python

### With Home Assistant (via the `unifiprotect` integration)

This requires at least `v0.10` of the `unifiprotect` integration to work.

1. Make sure you have the _Community_ [SSH & Web Terminal Add-On](https://github.com/hassio-addons/addon-ssh) install
2. Open an SSH or Web terminal to the add-on
3. Run

   ```bash
   docker exec -it homeassistant bash
   ```

Use `/config/ufp-data` for your `-o` argument below.

### Without Home Assistant

1. Ensure Python 3.9+ is installed
2. Install pyunifiprotect by issuing this command: `pip3 install pyunifiprotect`

Use `./ufp-data` for your `-o` argument below.

## Generate Data

Inside of the Python environment from above, run the following command. If you are using Home Assistant, use `-o /config/ufp-data` so it will output data in your config folder to make it easy to get off of your HA instance.

```bash
unifi-protect generate-sample-data -o /path/to/ufp-data --actual -w 300 -v -U your-unifi-protect-username -P your-unifi-protect-password -a ip-address-to-unifi-protect
```

This will generate a ton of data from your Unifi Protect instance for 5 minutes. During this time, go do stuff with your sensor to trigger events. When it is all done, you will have a bunch of json files in `/path/to/ufp-data`. Download those and zip them up and send them to us.

It is recommended that you _do not_ post these files publically as they do have some senstive data in them related to your Unifi Network. If you would like you manually clean out the senstive data from these files, feel free.

The most cirtical data for you do remove are the `authUserId`, `accessKey`, and `users` keys from the `sample_bootstrap.json` file.
