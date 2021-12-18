#!/usr/bin/env python3

import os
import asyncio
import pathlib
from tplinkcloud import TPLinkDeviceManager
import yaml

class TPLinkController():
    def __init__(self, device_name):
        config_fn = os.path.join(
            pathlib.Path.home(),
            ".config", "aqi", "tplink-client.yml")
        config = yaml.safe_load(open(config_fn, "r"))
        if not device_name in config['devices']:
            raise(f"No such device '{device_name}' in config file '{config_fn}'")
        self.config = config['devices'][device_name]

    async def async_set_plug_state(self, onoff):
        print(self.config)
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

