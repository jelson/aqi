#!/usr/bin/env python3

from mylogging import say
import argparse
import binascii
import cherrypy
import datetime
import hashlib
import json
import pms5003db
import subprocess
import traceback

PORT = 15000

class SensorDataHandler():
    def __init__(self, config):
        self.config = config
        self.db = None
        self.password = config['password'].encode('utf-8')

    @cherrypy.expose
    @cherrypy.tools.json_in()
    def data(self):
        msg = cherrypy.request.json

        # check password -- secure method:
        if 'salt' in msg and 'auth' in msg:
            expected = hashlib.sha256(msg['salt'].encode('utf-8'))
            expected.update(self.password)

            actual = binascii.unhexlify(msg['auth'])
            if expected.digest() != actual:
                cherrypy.response.status = 403
                return

        # check password -- clowny method
        elif 'clowny-cleartext-password' in msg:
            if msg['clowny-cleartext-password'] != self.password:
                cherrypy.response.status = 403
                return

        # No password provided
        else:
            print("no auth data provided; denying request")
            cherrypy.response.status = 403
            return

        # prepare sensor data
        sensorid = msg['sensorid']
        sensordata = msg['sensordata']
        for rec in sensordata:
            rec['time'] = datetime.datetime.fromtimestamp(rec['time'])

        # create database if none exists
        if not self.db:
            self.db = pms5003db.PMS5003Database()

        try:
            self.db.insert_batch(sensorid, sensordata)
        except Exception as e:
            self.db = None
            print(f"exception inserting records: {e}")
            traceback.print_exc()
            cherrypy.response.status = 501

        # Notify any integrations that new data is available
        if self.config['dbus-notify']:
            subprocess.run([
                "dbus-send",
                "--system",
                "--type=signal",
                "/org/lectrobox/aqi",
                "org.lectrobox.aqi.NewDataAvailable",
                f"dict:string:int32:sensorid,{sensorid}"
            ])



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
    cherrypy.config.update({
        'server.socket_host': '::',
        'server.socket_port': PORT,
    })

    # enable SSL if configured
    if 'certpath' in config:
        cherrypy.config.update({
            'server.ssl_certificate': config['certpath'],
            'server.ssl_private_key': config['keypath'],
            'server.ssl_certificate_chain': config['chainpath'],
        })

    cherrypy.quickstart(SensorDataHandler(config))

main()
