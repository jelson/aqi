#!/usr/bin/env python3

import argparse
import binascii
import cherrypy
import datetime
import hashlib
import json
import os
import subprocess
import sys
import traceback
import yaml

# project libraries
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from common.mylogging import say
import pms5003db

class SensorDataHandler():
    def __init__(self, config):
        self.config = config
        self.db = pms5003db.PMS5003Database()
        self.bin_password = config['password'].encode('utf-8')

    @cherrypy.expose
    def mac_lookup(self, macaddr):
        db = self.db.get_raw_db()
        cursor = db.cursor()
        cursor.execute(
            "select name from sensordatav4_sensors where macaddr=%s",
            (macaddr,))
        result = cursor.fetchone()
        db.commit()
        if result:
            return result[0]
        else:
            cherrypy.response.status = 401
            return ""

    @cherrypy.expose
    @cherrypy.tools.json_in()
    def data(self):
        msg = cherrypy.request.json

        # check password -- secure method:
        if 'salt' in msg and 'auth' in msg:
            expected = hashlib.sha256(msg['salt'].encode('utf-8'))
            expected.update(self.bin_password)

            actual = binascii.unhexlify(msg['auth'])
            if expected.digest() != actual:
                print("auth mismatch")
                cherrypy.response.status = 403
                return

        # check password -- clowny method
        elif 'clowny-cleartext-password' in msg:
            if msg['clowny-cleartext-password'] != self.config['password']:
                print(f"password mismatch")
                cherrypy.response.status = 403
                return

        # No password provided
        else:
            print("no auth data provided; denying request")
            cherrypy.response.status = 403
            return

        # prepare sensor data
        sensorname = msg.get('sensorname', None)
        sensorid = msg.get('sensorid', None)
        sensordata = msg['sensordata']
        for rec in sensordata:
            rec['time'] = datetime.datetime.fromtimestamp(rec['time'])

        self.db.insert_batch(sensorname, sensorid, sensordata)

        # Notify any integrations that new data is available
        if self.config['dbus-notify']:
            subprocess.run([
                "dbus-send",
                "--system",
                "--type=signal",
                "/org/lectrobox/aqi",
                "org.lectrobox.aqi.NewDataAvailable",
                f"dict:string:string:sensorname,{sensorname}"
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
    config = yaml.safe_load(open(args.config_file))
    cherrypy.config.update({
        'server.socket_host': '::',
        'server.socket_port': config['listen-port'],
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
