#!/usr/bin/env python3

# To trigger, send a dbus message thusly:
#
# dbus-send --system --type=signal /org/lectrobox/aqi
# org.lectrobox.aqi.NewDataAvailable dict:string:string:sensorname,jer-bedroom
#

from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import dbus
import os
import sys

# project libraries
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server.pms5003db as pms5003db
from common.mylogging import say
import nest_controller
import tplink_controller

CONFIG = [
    {
        'sensorname': 'jer-office',
        'datatype': 'aqi2.5',
        'on-thresh': 40,
        'off-thresh': 15,
        'averaging-sec': 60,
        'onoff-func': nest_controller.NestController('Jer Entryway').fan_control,
    },
    {
        'sensorname': 'jer-bedroom',
        'datatype': 'aqi2.5',
        'on-thresh': 40,
        'off-thresh': 15,
        'averaging-sec': 60,
        'onoff-func': nest_controller.NestController('Jer Bedroom').fan_control,
    },
    {
        'sensorname': 'gracie-bedroom',
        'datatype': 'aqi2.5',
        'on-thresh': 35,
        'off-thresh': 10,
        'averaging-sec': 60,
        'onoff-func': tplink_controller.TPLinkController('Gracie Fan').set_plug_state,
    },
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
        sensorname = str(argdict['sensorname'])

        for c in CONFIG:
            if c['sensorname'] == sensorname:
                self.maybe_on_off(c)

    def maybe_on_off(self, c):
        aqi = round(self.get_oneminute_average(c), 2)
        msg = f"sensor {c['sensorname']} aqi now {aqi}"

        fan_is_on = c.get('fan-is-on', False)
        msg += f"; fan_on={fan_is_on}"

        if fan_is_on:
            if aqi <= c['off-thresh']:
                msg += f'; tripped: under off-threshold {c["off-thresh"]}'
                self.change_fan_state(c, False)
            else:
                msg += '; staying on'
        else:
            if aqi >= c['on-thresh']:
                msg += f'; tripped: over on-threshold {c["on-thresh"]}'
                self.change_fan_state(c, True)
            else:
                msg += '; staying off'

        say(msg)

    def get_oneminute_average(self, c):
        # Note, cursor() executes rollback to end a prior transaction.
        # Otherwise, the value of now() never changes
        db = self.pmsdb.get_raw_db()
        cursor = db.cursor()
        cursor.execute(
            """
            select
               avg("value") from sensordatav4_tsdb
            where
               sensorid=%s and
               datatype=%s and
               time > now() - interval '%s seconds'""", (
                self.pmsdb.get_sensorid_by_name(c['sensorname']),
                self.pmsdb.get_datatype_by_name(c['datatype']),
                c['averaging-sec'])
        )
        row = cursor.fetchone()
        db.rollback()
        return row[0]

    def change_fan_state(self, c, onoff):
        c['fan-is-on'] = onoff
        c['onoff-func'](onoff)


def main():
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    ch = AQIChangeHandler(bus)  # noqa: F841
    loop = GLib.MainLoop()
    loop.run()


main()
