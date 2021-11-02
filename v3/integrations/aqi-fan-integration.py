#!/usr/bin/env python3

# To trigger, send a dbus message thusly:
#
# dbus-send --system --type=signal /org/lectrobox/aqi org.lectrobox.aqi.NewDataAvailable  dict:string:int32:sensorid,1
#

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import dbus
import nest_controller
import os
import psycopg2
import sys

# project libraries
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server.pms5003db as pms5003db

CONFIG = [
    {
        'sensorid': 1,
        'on-thresh': 30,
        'off-thresh': 5,
        'averaging-sec': 60,
        'onoff-func': nest_controller.NestController('Jer Entryway').fan_control,
    }
]

class AQIChangeHandler:
    def __init__(self, bus):
        bus.add_signal_receiver(
            self.NewDataAvailable,
            path='/org/lectrobox/aqi',
            signal_name='NewDataAvailable',
        )
        self.pmsdb = pms5003db.PMS5003Database()

    # dbus signal handler
    def NewDataAvailable(self, *args, **kwargs):
        argdict = dict(args[0])
        sensorid = int(argdict['sensorid'])

        for c in CONFIG:
            if c['sensorid'] == sensorid:
                self.maybe_on_off(c)

    def maybe_on_off(self, c):
        aqi = self.get_oneminute_average(c)
        print(f"sensor id {c['sensorid']} aqi now {aqi}")

        fan_is_on = c.get('fan-is-on', False)

        if fan_is_on and aqi <= c['off-thresh']:
            self.change_fan_state(c, False)
        elif (not fan_is_on) and aqi >= c['on-thresh']:
            self.change_fan_state(c, True)

    def get_oneminute_average(self, c):
        cursor = self.pmsdb.get_raw_db().cursor()
        cursor.execute(
            'select avg("aqi2.5") from particulatev3 where sensorid=%s and time > now() - interval \'%s seconds\'',
            (c['sensorid'], c['averaging-sec'])
        )
        row = cursor.fetchone()
        return(row[0])

    def change_fan_state(self, c, onoff):
        c['fan-is-on'] = onoff
        print(f'SensorID {c["sensorid"]} tripped over threshold')
        c['onoff-func'](onoff)

def main():
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    ch = AQIChangeHandler(bus)
    loop = GLib.MainLoop()
    loop.run()

main()
