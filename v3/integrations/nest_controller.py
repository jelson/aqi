#!/usr/bin/env python3

import json
import os
import pathlib
import requests
import yaml

class NestController():
    def __init__(self, device_name):
        config_fn = os.path.join(
            pathlib.Path.home(),
            ".config", "aqi", "nest-client.yml")
        config = yaml.safe_load(open(config_fn, "r"))
        self.config = config['client_config']
        if not device_name in config['devices']:
            raise(f"No such device '{device_name}' in config file '{config_fn}'")
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
        print(f"Sending request to {url}: {json_body}")
        if json_body:
            resp = requests.post(url, headers=headers, json=json_body)
        else:
            resp = requests.get(url, headers=headers)

        json_response = resp.json()
        print(f"Got response, status {resp.status_code}: {json.dumps(json_response, indent=True)}")
        return json_response

    def list_all_devices(self):
        return self._execute_request("{control_url}/enterprises/{project}/devices".format(**self.config))

    def get_status(self):
        return self._execute_request("{control_url}/enterprises/{project}/devices/{device}".format(**self.config))

    def _command_url(self):
        return "{control_url}/enterprises/{project}/devices/{device}:executeCommand".format(**self.config)

    def fan_control(self, onoff):
        if onoff:
            params = {
                "timerMode": "ON",
                "duration": "5400s", # 90 minutes

            }
        else:
            params = {
                "timerMode": "OFF",
            }

        self._execute_request(self._command_url(), json_body = {
            "command": "sdm.devices.commands.Fan.SetTimer",
            "params": params
        })

def main():
    controller = NestController('Jer Entryway')
    controller.list_all_devices()
    controller.get_status()

    controller = NestController('Jer Bedroom')
    controller.get_status()

if __name__ == '__main__':
    main()
