# HTTP client that takes sensor data and POSTs it to a waiting listener

import binascii
import datetime
import hashlib
import os
import random
import requests
import string
import sys

# project libraries
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from common.mylogging import say
import common.util

# Build an argparse parser for standard arguments for clients: sensor id, url and password
def build_parser(parser):
    parser.add_argument(
        '--sensor-id', '-s',
        help="Sensor ID",
        type=common.util.gtzero,
        action='store',
        required=True,
    )
    parser.add_argument(
        '--url', '-u',
        help="URL to post to",
        action='store',
        required=True,
    )
    parser.add_argument(
        '--password', '-p',
        help="Password for server",
        action='store',
        required=True,
    )
    parser.add_argument(
        '--verbose', '-v',
        help="Verbose operation; print records as they are received",
        action='store_true',
        default=False,
    )

class DataClient:
    def __init__(self, args):
        self.sensorid = args.sensor_id
        self.url = args.url
        self.password = args.password.encode('utf-8')
        self.session = requests.Session()

    def insert_batch(self, recordlist):
        say("sensor id {}: posting {} records from {} to {}".format(
            self.sensorid, len(recordlist),
            recordlist[0]['time'], recordlist[-1]['time']))

        for rec in recordlist:
            if isinstance(rec['time'], datetime.datetime):
                rec['time'] = rec['time'].timestamp()

        payload = {
            'sensorid': self.sensorid,
            'sensordata': recordlist,
        }

        # add authenticator
        payload['salt'] = ''.join(random.choices(string.ascii_uppercase, k=20))
        auth = hashlib.sha256(payload['salt'].encode('utf-8'))
        auth.update(self.password)
        payload['auth'] = auth.digest().hex()

        try:
            retval = self.session.post(self.url, json=payload)
        except Exception as e:
            say(f"failed to http post: {e}")
            return False

        if retval.status_code == 200:
            return True
        else:
            say(f"failed to http post: got http status {retval.status_code}")
            return False
