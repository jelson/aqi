#!/usr/bin/env python3

# PMS5003-aware database layer; interfaces with the generic database
# helper underneath, but knows the names of the database, table, and
# columns; annotates each record with a sensor id; and computes AQI
# from the raw PM2.5 value for each record.

from mylogging import say
import aqi
import database

COLNAMES = [
    'time',
    'sensorid',
    'pm1.0',
    'pm2.5',
    'pm10.0',
    'aqi2.5',
]

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
            tablename="particulatev3",
            column_list=COLNAMES,
        )

    def insert_batch(self, sensorid, recordlist):
        say("sensor id {}: writing {} records from {} to {}".format(
            sensorid, len(recordlist),
            recordlist[0]['time'], recordlist[-1]['time']))

        for record in recordlist:
            record['sensorid'] = sensorid
            record['aqi2.5'] = convert_aqi(record['pm2.5'])

        self.db.insert_batch(recordlist)
