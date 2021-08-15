#!/usr/bin/env python3

from logging import say
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
            record['aqi2.5'] = int(aqi.to_iaqi(
                aqi.POLLUTANT_PM25,
                record['pm2.5'],
                algo=aqi.ALGO_EPA))
        self.db.insert_batch(recordlist)
