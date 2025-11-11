#!/usr/bin/env python3

from tplinkcloud import TPLinkDeviceManager
import asyncio
import os
import pathlib
import sys
import yaml

# project libraries
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.mylogging import say


class TPLinkController():
    def __init__(self, device_name):
        config_fn = os.path.join(
            pathlib.Path.home(),
            ".config", "aqi", "tplink-client.yml")
        config = yaml.safe_load(open(config_fn, "r"))
        if device_name not in config['devices']:
            raise Exception(f"No such device '{device_name}' in config file '{config_fn}'")
        self.config = config['devices'][device_name]

    async def async_set_plug_state(self, onoff):
        say(f"Trying to set {self.config['username']}, "
            f"device {self.config['device_name']} to {onoff}")
        device_manager = TPLinkDeviceManager(self.config['username'], self.config['password'])
        device = await device_manager.find_device(self.config['device_name'])
        if not device:
            raise Exception(f"Could not find {self.config['device_name']}")
        if onoff:
            await device.power_on()
        else:
            await device.power_off()

    def set_plug_state(self, onoff):
        asyncio.run(self.async_set_plug_state(onoff))


if __name__ == '__main__':
    gracie_fan = TPLinkController("Gracie Fan")
    gracie_fan.set_plug_state(False)
