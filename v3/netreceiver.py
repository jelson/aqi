#!/usr/bin/env python3

from mylogging import say
import argparse
import cherrypy
import datetime
import json
import pms5003db
import socket

PORT = 15000

class SensorDataHandler():
    def __init__(self):
        self.db = pms5003db.PMS5003Database()

    @cherrypy.expose
    @cherrypy.tools.json_in()
    def data(self):
        msg = cherrypy.request.json
        sensorid = msg['sensorid']
        sensordata = msg['sensordata']
        for rec in sensordata:
            rec['time'] = datetime.datetime.fromtimestamp(rec['time'])
        self.db.insert_batch(sensorid, sensordata)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-l", "--log",
        help='Filename to log to',
        action='store'
    )
    parser.add_argument(
        "-c", "--config-file",
        help='Path to config file',
        action='store',
        required=True,
    )
    args = parser.parse_args()
    if args.log:
        logging.open_logfile(args.log)
    config = json.load(open(args.config_file))
    server = SensorDataHandler()
    cherrypy.config.update({
        'server.socket_host': '::',
        'server.socket_port': PORT,
        'server.ssl_certificate': config['certpath'],
        'server.ssl_private_key': config['keypath'],
        'server.ssl_certificate_chain': config['chainpath'],
    })
    cherrypy.quickstart(SensorDataHandler())

main()
