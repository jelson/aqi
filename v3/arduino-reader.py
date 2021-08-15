#!/usr/bin/env python3

# This file is for the v2 configuration:
#
# * PMS5003 sensor attached to an Arduino
#
# * Arduino is running a sketch that gets reads data from the sensor
#   and writes JSON-formatted data to its serial port
#
# * Arduino plugged into a Linux machine running this script, which
#   reads the JSON-formatted data and writes it to a postgres database
#   assumed to be running on the same machine.
#
# This configuration has been supplanted by the v3 configuration where
# the sensor is attached to an RPi which HTTP posts the JSON-formatted
# data to an HTTP server colocated with the database.
#
# If we ever wanted the Arduino in the loop, but writing to a remote
# database rather than a local one, this script could take an extra
# argument and set db to an instance of httpclient.
#

MAX_CACHE_SIZE = 15

from mylogging import say
import argparse
import datetime
import json
import pms5003db

def read_forever(db, sensorid, infile):
    cache = []
    while True:
        line = infile.readline()
        if not line:
            say("Got EOF! Terminating")
            return
        line = line.rstrip()
        if not line:
            continue

        # get data sent by arduino and timestamp it
        data = json.loads(line)
        data['time'] = datetime.datetime.now()

        # append to cache
        cache.append(data)

        # if cache is full, dump to database
        if len(cache) >= MAX_CACHE_SIZE:
            db.insert_batch(sensorid, cache)
            cache.clear()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d", "--device",
        help="Device file to read from",
        action='store',
        required='true',
    )
    parser.add_argument(
        "-s", "--sensor-id",
        help="Numeric sensor ID to write to database",
        action='store',
        required='true',
    )
    parser.add_argument(
        "-l", "--log",
        help='Filename to log to',
        action='store'
    )
    args = parser.parse_args()
    if args.log:
        mylogging.open_logfile(args.log)
    say(f"Starting; args: {args}")

    # open input file
    infile = open(args.device, "r")
    say(f"Opened input file {args.device}")

    # validate sensor id
    sensorid = int(args.sensor_id)
    if sensorid <= 0:
        say("Invalid sensor ID, must be >0")
        sys.exit(1)

    # open database
    db = pms5003db.PMS5003Database()

    # read forever
    read_forever(db, sensorid, infile)

    # should hopefully never be reached
    say("Read failed! Exiting!")

main()
