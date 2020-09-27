#!/usr/bin/env python3

import pandas
import sys
import os
import json
import aqi

import matplotlib.patches as patches

def process(filename):
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
    df = df.rolling(60).mean()
    df = df.dropna()
    df['aqi'] = df['pm2.5'].apply(lambda x: float(aqi.to_iaqi(
        aqi.POLLUTANT_PM25, x, algo=aqi.ALGO_EPA)))
    print(df)

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
    process(filename)

if __name__ == "__main__":
    main()
