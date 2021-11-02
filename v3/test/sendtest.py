#!/usr/bin/env python3

# Tests posting to the net receiver with synthetic data

# python standard libraries
import argparse
import datetime
import os
import sys

# project libraries
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import client.httpclient as httpclient
import common.util


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

    retval = client.insert_batch(records)
    print(f"Retval: {retval}")

def main():
    parser = argparse.ArgumentParser(sys.argv[0])
    httpclient.build_parser(parser)
    parser.add_argument(
        '--num-records', '-n',
        help="Number of records to insert",
        type=common.util.gtzero,
        action='store',
        required=True,
    )
    parser.add_argument(
        '--requests', '-r',
        help='Number of requests to make',
        type=common.util.gtzero,
        action='store',
        default='1',
    )
    args = parser.parse_args(sys.argv[1:])
    client = httpclient.DataClient(args)
    for i in range(args.requests):
        test(client, args)

main()
