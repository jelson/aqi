#!/usr/bin/env python3

import pandas
import sys
import os
import json
import aqi
import datetime
import psycopg2
import psycopg2.extras

import matplotlib.patches as patches

def get_data(filename):
    lines = open(filename).readlines()
    lines = map(lambda x: x.rstrip(), lines)

    def get_fields(line):
        l = line.split(']')
        retval = {}
        retval['date'] = l[0][1:]
        retval.update(json.loads(l[1]))
        return retval

    lines = map(get_fields, lines)

    df = pandas.DataFrame(lines)
    df['date'] = pandas.to_datetime(
        df['date'],
        format='%d/%m/%y - %H:%M:%S:%f',
    )

    df = df.set_index('date')
    df = df.dropna()
    df['aqi'] = df['pm2.5'].apply(lambda x: float(aqi.to_iaqi(
        aqi.POLLUTANT_PM25, x, algo=aqi.ALGO_EPA)))
    print(df)
    return df


def insert(df):
    conn = psycopg2.connect(database="airquality")
    cursor = conn.cursor()
    now = datetime.datetime.now()
    data = [
        (now - datetime.timedelta(seconds=10), 10, 25, 100, 1000),
        (now - datetime.timedelta(seconds=9), 11, 26, 101, 1001),
        (now - datetime.timedelta(seconds=8), 12, 27, 102, 1002),
        (now - datetime.timedelta(seconds=7), 13, 28, 103, 1003),
    ]
    insert_query = 'insert into particulate (time, pm10, pm25, pm100, aqi) values %s'
    df = df.copy()
    df.reset_index(inplace=True)
    psycopg2.extras.execute_values(
        cursor,
        insert_query,
        df.values,
        template=None,
    )
    conn.commit()

def graph(df):
    df = df.rolling(60).mean()
    plot = df[['pm1.0', 'pm2.5', 'pm10.0']].plot(grid=True, figsize=(20, 10))
    plot.set_title("Jer - Particulate Concentrations\n60-second rolling avg of 1hz data")
    plot.set_xlabel("date/time")
    plot.set_ylabel("ug/m3")
    plotname = os.path.splitext(filename)[0] + ".png"
    plot.figure.savefig(plotname)

    plot = df[['aqi']].plot(grid=True, figsize=(20, 10))
    plot.set_title("Jer - AQI from PM2.5\n60-second rolling avg of 1hz data")
    plot.set_ylim(bottom=0)
    plot.set_xlabel("date/time")
    plot.set_ylabel("AQI from PM2.5")
    rec = patches.Rectangle((0, 0), width=2000, height=50, fill=True,facecolor='green')
    plot.add_patch(rec)
    plotname = os.path.splitext(filename)[0] + ".aqi.png"
    plot.figure.savefig(plotname)

def main():
    filename = sys.argv[1]
    df = get_data(filename)
    insert(df)

if __name__ == "__main__":
    main()
