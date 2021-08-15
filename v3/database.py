#!/usr/bin/env python3

# Generic database interface for writing batches of records to a
# postgres database from a list of dicts that map column name to a
# value.

from logging import say
import psycopg2
import psycopg2.extras

class DatabaseBatcher:
    def __init__(self, dbname, tablename, column_list):
        self.column_list = column_list
        self.db = psycopg2.connect(database=dbname)
        quoted = [f'"{col}"' for col in column_list]
        self.stmt = f'insert into {tablename} ({",".join(quoted)}) values %s'

    # Data is a list of dicts mapping column name to value
    def insert_batch(self, recordlist):
        values = []
        for rec in recordlist:
            values.append([rec[col] if col in rec else None for col in self.column_list])

        cursor = self.db.cursor()
        psycopg2.extras.execute_values(
            cursor,
            self.stmt,
            values,
            template=None,
        )

        self.db.commit()
        say(f"{len(recordlist)} records committed")

