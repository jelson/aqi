#!/usr/bin/env python3

# read PMS3001 data from the serial port. timestamp each line when it
# arrives. batch into 30-record chunks and insert all records into the
# database. also write json-formatted records to stdout.

import aqi
import argparse
import datetime
import json
import psycopg2
import psycopg2.extras
import sys

MAX_CACHE_SIZE = 30

logfile = sys.stdout

def say(s):
    if logfile:
        logfile.write(s)
        logfile.write("\n")

def insert_batch(db, data):
    sys.stderr.write(f"inserting {len(data)} records\n")
    insert_query = 'insert into particulate (time, pm10, pm25, pm100, aqi) values %s'
    cursor = db.cursor()
    psycopg2.extras.execute_values(
        cursor,
        insert_query,
        data,
        template=None,
    )
    db.commit()


def line_arrived(cache, db, t, line):
    data = json.loads(line)

    printable_data = data.copy()
    printable_data['time'] = t.timestamp()
    printable_data['ftime'] = t.strftime("%Y-%m-%d %H:%M:%S.%f")
    say(json.dumps(printable_data))
    sys.stdout.flush()

    data['time'] = t
    data['aqi'] = int(aqi.to_iaqi(
        aqi.POLLUTANT_PM25,
        data['pm2.5'],
        algo=aqi.ALGO_EPA))


    db_record = [
        data['time'],
        data['pm1.0'],
        data['pm2.5'],
        data['pm10.0'],
        data['aqi'],
    ]

    cache.append(db_record)

    if len(cache) >= MAX_CACHE_SIZE:
        insert_batch(db, cache)
        cache.clear()
                 
def read_forever(db, f):
    cache = []
    while True:
        line = f.readline()
        if not line:
            say("Got EOF! Terminating")
            return
        line = line.rstrip()
        if line:
            line_arrived(cache, db, datetime.datetime.now(), line)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-p", "--port",
        help="Port to read from",
        action='store',
        required='true',
    )
    parser.add_argument(
        "-l", "--log",
        help='Filename to log to',
        action='store'
    )
    args = parser.parse_args()
    say(f"Starting; args: {args}")
    if args.log:
        global logfile
        logfile = open(args.log, "a")
    infile = open(args.port, "r")
    say("Opened file")
    db = psycopg2.connect(database="airquality")
    read_forever(db, infile)
    say("Read failed!")

main()
