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

import argparse
import datacache
import datetime
import json
import os
import sys

# project libraries
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import common.mylogging
from common.mylogging import say
import httpclient

def read_forever(infile, cache):
    say("Starting to read from sensor")
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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-d", "--device",
        help="Device file to read from",
        action='store',
        required='true',
    )
    parser.add_argument(
        "-l", "--log",
        help='Filename to log to',
        action='store'
    )
    httpclient.build_parser(parser)
    args = parser.parse_args()

    # set logging output
    if args.log:
        common.mylogging.open_logfile(args.log)
    say(f"Starting; args: {args}")

    # open input file
    infile = open(args.device, "r")
    say(f"Opened input file {args.device}")

    # create a cache
    cache = datacache.DataCache(args)

    # read forever
    read_forever(infile, cache)

    # should hopefully never be reached
    say("Read failed! Exiting!")

main()
