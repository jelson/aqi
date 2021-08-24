# HTTP client that takes sensor data and POSTs it to a waiting listener

from mylogging import say
import binascii
import datetime
import hashlib
import random
import requests
import string
import util

# Build an argparse parser for standard arguments for clients: sensor id, url and password
def build_parser(parser):
    parser.add_argument(
        '--sensor-id', '-s',
        help="Sensor ID",
        type=util.gtzero,
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
        payload['auth'] = binascii.hexlify(auth.digest())

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
