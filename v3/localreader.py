#!/usr/bin/env python3

MAX_CACHE_SIZE = 15

from logging import say
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

        data = json.loads(line)

        # rename legacy fields

        data['time'] = datetime.datetime.now()
        cache.append(data)

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
        logging.open_logfile(args.log)
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
