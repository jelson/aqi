# HTTP client that takes sensor data and POSTs it to a waiting listener

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


# Build an argparse parser for standard arguments for clients: sensor id, url and password
def build_parser(parser):
    parser.add_argument(
        '--sensor-name', '-s',
        help="Sensor name",
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
        self.sensorname = args.sensor_name
        self.url = args.url
        self.password = args.password.encode('utf-8')
        self.session = requests.Session()
        self.cb = None

    def set_send_callback(self, cb):
        self.cb = cb

    def insert_batch(self, recordlist):
        say("sensor {}: posting {} records from {} to {}".format(
            self.sensorname, len(recordlist),
            recordlist[0]['time'], recordlist[-1]['time']))

        for rec in recordlist:
            if isinstance(rec['time'], datetime.datetime):
                rec['time'] = rec['time'].timestamp()

        payload = {
            'sensorname': self.sensorname,
            'sensordata': recordlist,
        }

        # add authenticator
        payload['salt'] = ''.join(random.choices(string.ascii_uppercase, k=20))
        auth = hashlib.sha256(payload['salt'].encode('utf-8'))
        auth.update(self.password)
        payload['auth'] = auth.digest().hex()

        try:
            retval = self.session.post(
                self.url,
                json=payload,
                timeout=30,
            )
        except Exception as e:
            say(f"failed to http post: {e}")
            return False

        if self.cb:
            try:
                self.cb(retval)
            except Exception as e:
                say(f"callback failed: {e}")

        if retval.status_code == 200:
            return True
        else:
            say(f"failed to http post: got http status {retval.status_code}")
            return False
