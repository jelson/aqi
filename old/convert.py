#!/usr/bin/env python3

# One-time use script to convert previous log file format into JSON
import json

out = {}
for line in open("old-airq").readlines():
    fields = line.split()
    if 'PM 1.0' in line:
        date = " ".join(fields[0:3])
        out['pm1.0'] = fields[6]
    if 'PM 2.5' in line:
        out['pm2.5'] = fields[6]
    if 'PM 10.0' in line:
        out['pm10'] = fields[6]
        print(f"{date} {json.dumps(out)}")

