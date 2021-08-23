# HTTP client that takes sensor data and POSTs it to a waiting listener

from mylogging import say
import datetime
import requests

class DataClient:
    def __init__(self, url):
        self.url = url

    def insert_batch(self, sensorid, recordlist):
        say("sensor id {}: posting {} records from {} to {}".format(
            sensorid, len(recordlist),
            recordlist[0]['time'], recordlist[-1]['time']))

        for rec in recordlist:
            if isinstance(rec['time'], datetime.datetime):
                rec['time'] = rec['time'].timestamp()

        payload = {
            'sensorid': sensorid,
            'sensordata': recordlist,
        }
        try:
            retval = requests.post(self.url, json=payload)
        except Exception as e:
            say(f"failed to http post: {e}")
            return False

        if retval.status_code == 200:
            return True
        else:
            say(f"failed to http post: got http status {retval.status_code}")
            return False