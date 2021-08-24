#!/usr/bin/env python3

# Tests posting to the net receiver with synthetic data

import argparse
import datetime
import sys

sys.path.append("..")
import httpclient


def test(client, args):
    t = datetime.datetime.now()
    records = []
    for i in range(args.num_records):
        records.append({
            'time': t,
            'pm1.0': i,
            'pm2.5': 100+i,
            'pm10.0': 1000+i,
        })
        t = t + datetime.timedelta(seconds=0.1)

    retval = client.insert_batch(sensor_id, records)
    print(f"Retval: {retval}")

def main():
    parser = argparse.ArgumentParser(sys.argv[0])
    parser.add_argument(
        '--url', '-u',
        help="URL to post to",
        action='store',
        required=True,
    )

    def gtzero(arg):
        arg = int(arg)
        if arg <= 0:
            raise argparse.ArgumentTypeError("argument must be > 0")
        return arg

    parser.add_argument(
        '--sensor-id', '-s',
        help="Sensor ID",
        type=gtzero,
        action='store',
        required=True,
    )
    parser.add_argument(
        '--num-records', '-n',
        help="Number of records to insert",
        type=gtzero,
        action='store',
        required=True,
    )
    parser.add_argument(
        '--password', '-p',
        help="Password for server",
        action='store',
        required=True,
    )
    parser.add_argument(
        '--requests', '-r',
        help='Number of requests to make',
        type=gtzero,
        action='store',
        default='1',
    )
    args = parser.parse_args(sys.argv[1:])

    client = httpclient.DataClient(args.url, args.password)
    for i in range(args.requests):
        test(client, args)

main()
