#!/usr/bin/env python3

import datetime
import os
import pandas as pd
import sys

# project libraries
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server.pms5003db as pms5003db

def read_as_dataframe(db, sensorname, datatype, time_start=None, time_end=None):
    sensor_id = db.get_sensorid_by_name(sensorname)
    datatype_id = db.get_datatype_by_name(datatype)

    if not sensor_id or not datatype_id:
        raise Exception("sensor or datatype not found")

    stmt = """
         select 
            time, value
         from
            sensordatav4_tsdb
         where
            sensorid=%s and datatype=%s
           """
    values = [sensor_id, datatype_id]

    if time_start:
        stmt += " and time >= %s "
        values.append(time_start)

    if time_end:
        stmt += " and time <= %s "
        values.append(time_end)

    stmt += "order by time"

    conn = db.get_raw_db()
    return pd.read_sql(stmt, conn, params=values)

db = pms5003db.PMS5003Database()
df = read_as_dataframe(
    db, "dave-shed", "pressure_hPa",
    time_start=datetime.datetime.now() - datetime.timedelta(days=1),
)
df = df.loc[df['value'] >= 900]
print(df)
print(df.describe())
