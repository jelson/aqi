#!/usr/bin/env python3

from mylogging import say
import argparse
import datetime
import http.server
import json
import pms5003db
import socket

PORT = 15000

class SensorDataHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        len = int(self.headers['Content-Length'])
        post_data = self.rfile.read(len)
        msg = json.loads(post_data)
        sensorid = msg['sensorid']
        sensordata = msg['sensordata']
        for rec in sensordata:
            rec['time'] = datetime.datetime.fromtimestamp(rec['time'])
        self.server.db.insert_batch(sensorid, sensordata)
        self.send_response(200)
        self.end_headers()

class SensorDataServer(http.server.ThreadingHTTPServer):
    def __init__(self, db):
        self.address_family = socket.AF_INET6
        super(SensorDataServer, self).__init__(("", PORT), SensorDataHandler)
        self.db = db

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-l", "--log",
        help='Filename to log to',
        action='store'
    )
    args = parser.parse_args()
    if args.log:
        logging.open_logfile(args.log)

    db = pms5003db.PMS5003Database()
    server = SensorDataServer(db)
    say(f"Starting on port {PORT}")
    server.serve_forever()

main()
