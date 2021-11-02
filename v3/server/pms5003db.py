#!/usr/bin/env python3

# PMS5003-aware database layer; interfaces with the generic database
# helper underneath, but knows the names of the database, table, and
# columns; annotates each record with a sensor id; and computes AQI
# from the raw PM2.5 value for each record.

import aqi
import os
import sys

# project libraries
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from common.mylogging import say
import server.database as database

# Convert PM2.5 to AQI. It seems that AQI is not defined above PM2.5
# of 500 so we just add to it linearly after that.
def convert_aqi(pm):
    if pm > 500:
        aqi_input = 500
        extra = pm - 500
    else:
        aqi_input = pm
        extra = 0

    aqi_output = int(aqi.to_iaqi(
        aqi.POLLUTANT_PM25,
        aqi_input,
        algo=aqi.ALGO_EPA))
    aqi_output += extra
    return aqi_output


class PMS5003Database:
    def __init__(self):
        self.db = database.DatabaseBatcher(
            dbname="airquality",
            tablename="sensordatav4",
            column_list=[
                'time',
                'sensorid',
                'datatype',
                'value',
            ]
        )

        cursor = self.db.get_raw_db().cursor()
        # get the list of valid sensor ids
        cursor.execute("select name, id from sensordatav4_sensors")
        self.sensornames = {row[0]: row[1] for row in cursor.fetchall()}
        say(f"sensor names: {self.sensornames}")

        # get the list of valid data types
        cursor.execute("select name, id from sensordatav4_types")
        self.datatypes = {row[0]: row[1] for row in cursor.fetchall()}
        say(f"data types: {self.datatypes}")

    def get_raw_db(self):
        return self.db.get_raw_db()

    def get_sensorid_by_name(self, sensorname):
        return self.sensornames.get(sensorname, None)

    def get_datatype_by_name(self, datatype):
        return self.datatypes.get(datatype, None)

    # sensorid is for backcompat and will go away soon
    def insert_batch(self, sensorname, sensorid, recordlist):
        if not sensorid:
            sensorid = self.get_sensorid_by_name(sensorname)
        if not sensorid:
            raise Exception(f"unknown sensor name {sensorname}")

        say("sensor {} (id {}): writing {} records from {} to {}".format(
            sensorname, sensorid, len(recordlist),
            recordlist[0]['time'], recordlist[-1]['time']))

        insertion_list = []

        for record in recordlist:
            time = record.pop('time')
            if 'pm2.5' in record:
                record['aqi2.5'] = convert_aqi(record['pm2.5'])
            for key, val in record.items():
                datatype = self.get_datatype_by_name(key)
                if not datatype:
                    raise Exception(f"sensor {sensorname} sent unknown field '{key}'")
                insertion_list.append({
                    'time': time,
                    'sensorid': sensorid,
                    'datatype': datatype,
                    'value': val,
                })

        self.db.insert_batch(insertion_list)
