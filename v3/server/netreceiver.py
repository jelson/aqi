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
import tempfile
import yaml

# project libraries
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from common.mylogging import say
from common import mylogging
import pms5003db


class SensorDataHandler():
    def __init__(self, config):
        self.config = config
        self.db = pms5003db.PMS5003Database()
        self.bin_password = config['password'].encode('utf-8')
        self.lookup_log = tempfile.NamedTemporaryFile(mode="w")

    @cherrypy.expose
    def recent_lookups(self):
        return open(self.lookup_log.name).read()

    @cherrypy.expose
    def mac_lookup(self, macaddr):
        db = self.db.get_raw_db()
        cursor = db.cursor()
        cursor.execute(
            "select name from sensordatav4_sensors where macaddr=%s",
            (macaddr,))
        result = cursor.fetchone()
        db.rollback()
        if result:
            sensorname = result[0]
        else:
            cherrypy.response.status = 401
            sensorname = None

        msg = f"Got lookup request for mac {macaddr}, returned {sensorname}"
        self.lookup_log.write(f"<p>{datetime.datetime.now()}: {msg}\n")
        self.lookup_log.flush()
        say(msg)
        return sensorname

    @cherrypy.expose
    def data(self):
        debugstr = "{}:{} {}".format(
            cherrypy.request.remote.ip,
            cherrypy.request.remote.port,
            cherrypy.request.headers.get('User-Agent', 'no-user-agent')
        )

        body = cherrypy.request.body.read()
        try:
            msg = json.loads(body)
        except Exception:
            say(f"{debugstr}: got invalid json document: {body}")
            cherrypy.response.status = 400
            return

        # check password -- secure method:
        if 'salt' in msg and 'auth' in msg:
            expected = hashlib.sha256(msg['salt'].encode('utf-8'))
            expected.update(self.bin_password)

            actual = binascii.unhexlify(msg['auth'])
            if expected.digest() != actual:
                say("auth mismatch")
                cherrypy.response.status = 403
                return

        # check password -- clowny method
        elif 'clowny-cleartext-password' in msg:
            if msg['clowny-cleartext-password'] != self.config['password']:
                say("password mismatch")
                cherrypy.response.status = 403
                return

        # No password provided
        else:
            say("no auth data provided; denying request")
            cherrypy.response.status = 403
            return

        # prepare sensor data
        sensorname = msg.get('sensorname', None)
        sensorid = msg.get('sensorid', None)
        sensordata = msg['sensordata']
        for rec in sensordata:
            rec['time'] = datetime.datetime.fromtimestamp(rec['time'])

        self.db.insert_batch(sensorname, sensorid, sensordata, debugstr=debugstr)

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
        mylogging.open_logfile(args.log)
    config = yaml.safe_load(open(args.config_file))
    cherrypy.config.update({
        'server.socket_host': '::',
        'server.socket_port': config['listen-port'],
        'server.socket_timeout': 30,
    })

    if config.get('is-proxy', False):
        cherrypy.config.update({
            'tools.proxy.on': True,
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
