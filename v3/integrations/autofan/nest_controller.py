#!/usr/bin/env python3

import json
import os
import pathlib
import requests
import yaml


class NestController():
    CONFIG_FILE = os.path.join(pathlib.Path.home(), ".config", "aqi", "nest-client.yml")

    @staticmethod
    def configured_device_names():
        config = yaml.safe_load(open(NestController.CONFIG_FILE, "r"))
        return list(config['devices'].keys())

    def __init__(self, device_name):
        config = yaml.safe_load(open(self.CONFIG_FILE, "r"))
        self.config = config['client_config']
        if device_name not in config['devices']:
            raise Exception(f"No such device '{device_name}' in config file '{self.CONFIG_FILE}'")
        self.config.update(config['devices'][device_name])

    def _execute_request(self, url, json_body=None):
        # First, get a token using the refresh token
        params = {
            'client_id': self.config['client_id'],
            'client_secret': self.config['client_secret'],
            'refresh_token': self.config['refresh_token'],
            'grant_type': 'refresh_token',
        }
        resp = requests.post(self.config['oauth_url'], params=params)
        if not resp or resp.status_code != 200:
            raise Exception(f"Failed to refresh token: {resp}")
        token_info = resp.json()

        # Now, execute the request
        headers = {
            'Authorization': 'Bearer ' + token_info['access_token'],
        }
        if json_body:
            resp = requests.post(url, headers=headers, json=json_body)
        else:
            resp = requests.get(url, headers=headers)

        return resp.json()

    def list_all_devices(self):
        return self._execute_request(
            "{control_url}/enterprises/{project}/devices".format(**self.config))

    def get_status(self):
        return self._execute_request(
            "{control_url}/enterprises/{project}/devices/{device}".format(**self.config))

    def _command_url(self):
        return ("{control_url}/enterprises/{project}/devices/{device}:executeCommand"
                .format(**self.config))

    def fan_control(self, onoff):
        if onoff:
            params = {
                "timerMode": "ON",
                "duration": "5400s",  # 90 minutes

            }
        else:
            params = {
                "timerMode": "OFF",
            }

        return self._execute_request(self._command_url(), json_body={
            "command": "sdm.devices.commands.Fan.SetTimer",
            "params": params
        })


def _print_status(device_name, status):
    traits = status.get('traits', {})

    fan = traits.get('sdm.devices.traits.Fan', {})
    fan_mode = fan.get('timerMode', 'unknown')
    fan_timeout = fan.get('timerTimeout', None)

    hvac = traits.get('sdm.devices.traits.ThermostatHvac', {})
    hvac_status = hvac.get('status', 'unknown')

    thermo_mode = traits.get('sdm.devices.traits.ThermostatMode', {}).get('mode', 'unknown')

    temp_trait = traits.get('sdm.devices.traits.Temperature', {})
    ambient_c = temp_trait.get('ambientTemperatureCelsius')
    ambient_f = f"{ambient_c * 9/5 + 32:.1f}°F" if ambient_c is not None else 'unknown'

    humidity = traits.get('sdm.devices.traits.Humidity', {}).get('ambientHumidityPercent', 'unknown')

    print(f"Device:      {device_name}")
    print(f"Temperature: {ambient_f}")
    print(f"Humidity:    {humidity}%")
    print(f"HVAC:        {hvac_status}")
    print(f"Mode:        {thermo_mode}")
    fan_line = f"Fan:         {fan_mode}"
    if fan_timeout:
        fan_line += f" (until {fan_timeout})"
    print(fan_line)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Nest thermostat controller')
    parser.add_argument('--device', '-d', default='Jer Entryway',
                        help='Device name from config (default: "Jer Entryway")')
    parser.add_argument('--json', action='store_true',
                        help='Print raw JSON output only')

    subparsers = parser.add_subparsers(dest='command', required=True)

    subparsers.add_parser('status', help='Get device status')
    subparsers.add_parser('list-devices', help='List all devices')

    fan_parser = subparsers.add_parser('fan', help='Control the fan')
    fan_parser.add_argument('onoff', choices=['on', 'off'], help='Turn fan on or off')

    args = parser.parse_args()

    def print_json(data):
        print(json.dumps(data, indent=2))

    if args.command == 'list-devices' and not args.json:
        for name in NestController.configured_device_names():
            print(name)
        return

    controller = NestController(args.device)

    if args.command == 'status':
        status = controller.get_status()
        if args.json:
            print_json(status)
        else:
            _print_status(args.device, status)

    elif args.command == 'list-devices':
        print_json(controller.list_all_devices())

    elif args.command == 'fan':
        onoff = args.onoff == 'on'
        result = controller.fan_control(onoff)
        if args.json:
            print_json(result)
        else:
            print(f"Fan turned {'on' if onoff else 'off'}.")


if __name__ == '__main__':
    main()
