#!/usr/bin/env python3

# PMS5003-aware database layer; interfaces with the generic database
# helper underneath, but knows the names of the database, table, and
# columns; annotates each record with a sensor id; and computes AQI
# from the raw PM2.5 value for each record.

import aqi
import os
import sys
import psycopg2
import time

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
    DBNAME = "airquality"

    def __init__(self):
        self._db = None

        db = self.get_raw_db()
        cursor = db.cursor()
        # get the list of valid sensor ids
        cursor.execute("select name, id from sensordatav4_sensors")
        self.sensornames = {row[0]: row[1] for row in cursor.fetchall()}
        say(f"sensor names: {self.sensornames}")

        # get the list of valid data types
        cursor.execute("select name, id from sensordatav4_types")
        self.datatypes = {row[0]: row[1] for row in cursor.fetchall()}
        say(f"data types: {self.datatypes}")
        db.rollback()

    def get_raw_db(self):
        # Test the database to see if it works by executing a
        # rollback. If not, close and reopen.
        for i in range(2):
            try:
                if not self._db:
                    say(f"Opening connection to database {self.DBNAME}")
                    self._db = psycopg2.connect(database=self.DBNAME)
                self._db.rollback()
                return self._db
            except psycopg2.InterfaceError as e:
                say(f"Exception using db; closing and reopening: {e}")
                self._db = None

        say("Could not get working database - exiting")
        sys.exit(1)

    def get_sensorid_by_name(self, sensorname):
        return self.sensornames.get(sensorname, None)

    def get_datatype_by_name(self, datatype):
        return self.datatypes.get(datatype, None)

    def _insert_expanded(self, insertion_list):
        db = self.get_raw_db()
        cursor = db.cursor()
        psycopg2.extras.execute_values(
            cursor,
            "insert into sensordatav4_tsdb (time, sensorid, datatype, value, received_at) values %s",
            insertion_list,
            template="(%(time)s, %(sensorid)s, %(datatype)s, %(value)s, now())",
        )

        # find the most recent record of each datatype and update the
        # "latest records" list. Latest is a map from each datatype to
        # the most recent record of that datatype.
        latest = {}
        for insertion in insertion_list:
            datatype = insertion['datatype']
            if not datatype in latest or latest[datatype]['time'] < insertion['time']:
                latest[datatype] = insertion
        psycopg2.extras.execute_values(
            cursor,
            """
            insert into sensordatav4_latest (sensorid, datatype, time, value, received_at)
            values %s
            on
               conflict (sensorid, datatype)
            do
                update set
                    time=excluded.time,
                    value=excluded.value,
                    received_at=excluded.received_at
            """,
            list(latest.values()),
            template="(%(sensorid)s, %(datatype)s, %(time)s, %(value)s, now())",
        )
        db.commit()

    # sensorid is for backcompat and will go away soon
    MAX_DB_INSERTS_PER_BATCH = 2000
    MAX_INSERT_TIME_SEC = 20

    def insert_batch(self, sensorname, sensorid, recordlist, debugstr=None):
        if not sensorid:
            sensorid = self.get_sensorid_by_name(sensorname)
        if not sensorid:
            raise Exception(f"unknown sensor name {sensorname}")
        if not recordlist:
            raise Exception(f"{sensorname}: empty record list")

        # write log message
        logmsg = "sensor {} (id {}): writing {} records from {} to {}".format(
            sensorname, sensorid, len(recordlist),
            recordlist[0]['time'], recordlist[-1]['time'])
        if debugstr:
            logmsg = debugstr + ": " + logmsg
        say(logmsg)

        # generate a list of rows to be inserted into the database
        # from the json record sent by the client
        insertion_list = []
        recnum = 0
        starttime = time.time()
        for record in recordlist:
            recnum += 1
            rectime = record.pop('time')
            # if this record has a PM2.5 record, also compute the EPA
            # AQI2.5 value for it
            if 'pm2.5' in record:
                record['aqi2.5'] = convert_aqi(record['pm2.5'])

            # for each data type in this record, look up the datatype
            # id associated with that datatype name and prepare a
            # database row with that data and the record's time
            for key, val in record.items():
                datatype = self.get_datatype_by_name(key)
                if not datatype:
                    say(f"WARNING: sensor {sensorname} sent unknown field '{key}'")
                    continue
                insertion_list.append({
                    'time': rectime,
                    'sensorid': sensorid,
                    'datatype': datatype,
                    'value': val,
                })

            if len(insertion_list) > self.MAX_DB_INSERTS_PER_BATCH:
                self._insert_expanded(insertion_list)
                say(f"sensorid {sensorid}: batch write up to record {recnum}")
                insertion_list = []

                runtime = time.time() - starttime

                if runtime > self.MAX_INSERT_TIME_SEC:
                    say(f"sensorid {sensorid}: dropping the remainder; too many records")
                    return

        self._insert_expanded(insertion_list)
