"""
Unit tests for v3/server/pms5003db.py

Covers: AQI conversion, DB initialization, thread-local connection isolation,
record insertion/expansion, and latest-value upsert logic.
"""

import datetime
import os
import sys
import threading
from unittest.mock import MagicMock, call, patch

import psycopg2
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pms5003db import PMS5003Database, convert_aqi

# ── Fixture helpers ──────────────────────────────────────────────────────────

SENSOR_ROWS = [('jer-office', 1), ('jer-bedroom', 2)]
TYPE_ROWS = [
    ('pm1.0', 10001), ('pm2.5', 10002), ('aqi2.5', 10003), ('pm10.0', 10004),
]


def _make_init_conn():
    """A mock psycopg2 connection pre-loaded for PMS5003Database.__init__ queries."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchall.side_effect = [list(SENSOR_ROWS), list(TYPE_ROWS)]
    return conn, cursor


def _build_db():
    """Construct a PMS5003Database with mocked psycopg2; return (db, conn, cursor)."""
    conn, cursor = _make_init_conn()
    with patch('psycopg2.connect', return_value=conn):
        db = PMS5003Database()
    # Reset for use in tests
    cursor.fetchall.side_effect = None
    cursor.fetchall.return_value = []
    return db, conn, cursor


@pytest.fixture
def db():
    instance, _, _ = _build_db()
    return instance


@pytest.fixture
def db_conn():
    return _build_db()


# ── AQI conversion ───────────────────────────────────────────────────────────

class TestConvertAQI:
    def test_zero(self):
        assert convert_aqi(0) == 0

    def test_low_is_good_range(self):
        # PM2.5 = 6 is solidly "Good" (AQI 0–50)
        assert 0 < convert_aqi(6) <= 50

    def test_moderate_range(self):
        # PM2.5 ~ 35 is roughly AQI 100
        assert 90 <= convert_aqi(35) <= 110

    def test_at_500_boundary(self):
        assert convert_aqi(500) >= convert_aqi(499)

    def test_above_500_linear_extension(self):
        base = convert_aqi(500)
        assert convert_aqi(510) == base + 10
        assert convert_aqi(600) == base + 100

    def test_returns_int(self):
        for v in [0, 12, 35, 100, 500, 501]:
            assert isinstance(convert_aqi(v), int)

    def test_monotonically_increasing(self):
        values = [0, 6, 12, 35, 55, 150, 250, 350, 500, 510, 600]
        aqi_vals = [convert_aqi(v) for v in values]
        assert aqi_vals == sorted(aqi_vals)


# ── Initialization ───────────────────────────────────────────────────────────

class TestInit:
    def test_sensor_names_loaded(self, db):
        assert db.sensornames == {'jer-office': 1, 'jer-bedroom': 2}

    def test_datatype_names_loaded(self, db):
        assert db.datatypes == {
            'pm1.0': 10001, 'pm2.5': 10002,
            'aqi2.5': 10003, 'pm10.0': 10004,
        }

    def test_get_sensorid_known(self, db):
        assert db.get_sensorid_by_name('jer-office') == 1
        assert db.get_sensorid_by_name('jer-bedroom') == 2

    def test_get_sensorid_unknown(self, db):
        assert db.get_sensorid_by_name('no-such-sensor') is None

    def test_get_datatype_known(self, db):
        assert db.get_datatype_by_name('pm2.5') == 10002

    def test_get_datatype_unknown(self, db):
        assert db.get_datatype_by_name('no-such-type') is None


# ── Thread-local connection isolation ────────────────────────────────────────

class TestGetRawDb:
    def test_returns_connection(self, db_conn):
        db, conn, _ = db_conn
        assert db.get_raw_db() is conn

    def test_skips_rollback_when_status_ready(self, db_conn):
        """No round-trip when connection is already clean."""
        db, conn, _ = db_conn
        conn.status = psycopg2.extensions.STATUS_READY
        conn.rollback.reset_mock()
        db.get_raw_db()
        conn.rollback.assert_not_called()

    def test_calls_rollback_when_not_status_ready(self, db_conn):
        """Rollback is issued when a transaction is open."""
        db, conn, _ = db_conn
        conn.status = psycopg2.extensions.STATUS_IN_TRANSACTION
        conn.rollback.reset_mock()
        db.get_raw_db()
        conn.rollback.assert_called_once()

    def test_new_thread_has_no_connection(self, db):
        """A new thread must not inherit the main thread's _local.db."""
        result = {}

        def check():
            result['has_conn'] = getattr(db._local, 'db', None) is not None

        t = threading.Thread(target=check)
        t.start()
        t.join()
        assert not result['has_conn']

    def test_new_thread_opens_own_connection(self, db):
        """When a new thread calls get_raw_db(), it opens its own connection."""
        new_conn = MagicMock()
        result = {}

        def get_conn():
            with patch('psycopg2.connect', return_value=new_conn):
                result['conn'] = db.get_raw_db()

        t = threading.Thread(target=get_conn)
        t.start()
        t.join()
        assert result['conn'] is new_conn

    def test_two_threads_get_different_connections(self, db):
        """Two concurrent threads must each get their own distinct connection."""
        results = {}

        def get_conn(key):
            with patch('psycopg2.connect', return_value=MagicMock()):
                results[key] = db.get_raw_db()

        t1 = threading.Thread(target=get_conn, args=('t1',))
        t2 = threading.Thread(target=get_conn, args=('t2',))
        t1.start(); t2.start()
        t1.join(); t2.join()
        assert results['t1'] is not results['t2']

    def test_reconnects_on_interface_error(self, db_conn):
        """A broken connection triggers reconnect on the same thread."""
        db, original_conn, _ = db_conn
        new_conn = MagicMock()
        original_conn.rollback.side_effect = psycopg2.InterfaceError("gone")

        with patch('psycopg2.connect', return_value=new_conn):
            result = db.get_raw_db()

        assert result is new_conn
        assert db._local.db is new_conn

    def test_exits_if_reconnect_also_fails(self, db_conn):
        """If both connection attempts fail, sys.exit(1) is called."""
        db, original_conn, _ = db_conn
        original_conn.rollback.side_effect = psycopg2.InterfaceError("gone")

        with patch('psycopg2.connect', side_effect=psycopg2.InterfaceError("still gone")):
            with pytest.raises(SystemExit) as exc:
                db.get_raw_db()
        assert exc.value.code == 1


# ── insert_batch ─────────────────────────────────────────────────────────────

class TestInsertBatch:
    T = datetime.datetime(2024, 6, 1, 12, 0, 0)

    def _records(self, n=1):
        return [
            {
                'time': self.T + datetime.timedelta(seconds=i),
                'pm1.0': float(i),
                'pm2.5': float(10 + i),
                'pm10.0': float(100 + i),
            }
            for i in range(n)
        ]

    def test_raises_on_unknown_sensor(self, db):
        with pytest.raises(Exception, match="unknown sensor"):
            db.insert_batch('no-such-sensor', None, self._records())

    def test_raises_on_empty_recordlist(self, db):
        with pytest.raises(Exception, match="empty"):
            db.insert_batch('jer-office', None, [])

    def test_resolves_sensorid_by_name(self, db):
        with patch.object(db, '_insert_expanded') as mock_insert:
            db.insert_batch('jer-office', None, self._records())
        rows = mock_insert.call_args[0][0]
        assert all(r['sensorid'] == 1 for r in rows)

    def test_uses_provided_sensorid_over_name_lookup(self, db):
        with patch.object(db, '_insert_expanded') as mock_insert:
            db.insert_batch('jer-office', 99, self._records())
        rows = mock_insert.call_args[0][0]
        assert all(r['sensorid'] == 99 for r in rows)

    def test_computes_aqi25_from_pm25(self, db):
        with patch.object(db, '_insert_expanded') as mock_insert:
            db.insert_batch('jer-office', None, self._records(1))
        rows = mock_insert.call_args[0][0]
        datatypes = {r['datatype'] for r in rows}
        assert 10003 in datatypes  # aqi2.5

    def test_aqi25_value_matches_convert_aqi(self, db):
        pm_val = 35.0
        records = [{'time': self.T, 'pm2.5': pm_val}]
        with patch.object(db, '_insert_expanded') as mock_insert:
            db.insert_batch('jer-office', None, records)
        rows = mock_insert.call_args[0][0]
        aqi_rows = [r for r in rows if r['datatype'] == 10003]
        assert len(aqi_rows) == 1
        assert aqi_rows[0]['value'] == convert_aqi(pm_val)

    def test_unknown_field_is_skipped(self, db):
        records = [{'time': self.T, 'pm2.5': 5.0, 'unknown_sensor_field': 99.0}]
        with patch.object(db, '_insert_expanded') as mock_insert:
            db.insert_batch('jer-office', None, records)
        rows = mock_insert.call_args[0][0]
        # Only pm2.5 (10002) and its computed aqi2.5 (10003) should be present
        assert {r['datatype'] for r in rows} == {10002, 10003}

    def test_all_unknown_fields_still_calls_insert_expanded_with_empty_list(self, db):
        # Documents current behavior: _insert_expanded([]) is called even when
        # no valid fields were found. This is a known issue.
        records = [{'time': self.T, 'totally_unknown': 1.0}]
        with patch.object(db, '_insert_expanded') as mock_insert:
            db.insert_batch('jer-office', None, records)
        mock_insert.assert_called_once_with([])

    def test_mid_batch_flush_at_size_limit(self, db):
        """Batches exceeding MAX_DB_INSERTS_PER_BATCH flush mid-way."""
        # 5 records × 4 fields each (pm1.0, pm2.5, pm10.0, aqi2.5) = 20 rows.
        # With a limit of 5, we expect multiple flushes.
        with patch.object(db, '_insert_expanded') as mock_insert, \
             patch.object(PMS5003Database, 'MAX_DB_INSERTS_PER_BATCH', 5):
            db.insert_batch('jer-office', None, self._records(5))
        assert mock_insert.call_count >= 2

    def test_records_have_correct_timestamps(self, db):
        t0 = datetime.datetime(2024, 1, 1, 0, 0, 0)
        t1 = datetime.datetime(2024, 1, 1, 0, 0, 1)
        records = [
            {'time': t0, 'pm1.0': 1.0},
            {'time': t1, 'pm1.0': 2.0},
        ]
        with patch.object(db, '_insert_expanded') as mock_insert:
            db.insert_batch('jer-office', None, records)
        rows = mock_insert.call_args[0][0]
        times = [r['time'] for r in rows]
        assert t0 in times
        assert t1 in times


# ── _insert_expanded ─────────────────────────────────────────────────────────

class TestInsertExpanded:
    T1 = datetime.datetime(2024, 6, 1, 12, 0, 0)
    T2 = datetime.datetime(2024, 6, 1, 12, 0, 1)

    def _row(self, time, datatype, value, sensorid=1):
        return {'time': time, 'sensorid': sensorid, 'datatype': datatype, 'value': value}

    def test_calls_execute_values_twice(self, db_conn):
        """One execute_values for tsdb insert, one for latest upsert."""
        db, conn, _ = db_conn
        with patch('psycopg2.extras.execute_values') as mock_ev:
            db._insert_expanded([self._row(self.T1, 10001, 5.0)])
        assert mock_ev.call_count == 2

    def test_commits_after_insert(self, db_conn):
        db, conn, _ = db_conn
        with patch('psycopg2.extras.execute_values'):
            db._insert_expanded([self._row(self.T1, 10001, 5.0)])
        conn.commit.assert_called_once()

    def test_latest_takes_most_recent_for_same_datatype(self, db_conn):
        """When two rows share a datatype, the latest upsert uses the newer one."""
        db, conn, _ = db_conn
        rows = [
            self._row(self.T1, 10001, 5.0),   # earlier
            self._row(self.T2, 10001, 15.0),  # later, same datatype
        ]
        with patch('psycopg2.extras.execute_values') as mock_ev:
            db._insert_expanded(rows)

        # Second call is the latest upsert; its values list is the 3rd positional arg
        latest_values = mock_ev.call_args_list[1][0][2]
        assert len(latest_values) == 1
        assert latest_values[0]['value'] == 15.0
        assert latest_values[0]['time'] == self.T2

    def test_latest_one_entry_per_distinct_datatype(self, db_conn):
        """Each datatype gets exactly one entry in the latest upsert."""
        db, conn, _ = db_conn
        rows = [
            self._row(self.T1, 10001, 1.0),
            self._row(self.T1, 10002, 2.0),
            self._row(self.T2, 10002, 3.0),  # update 10002 with a later record
        ]
        with patch('psycopg2.extras.execute_values') as mock_ev:
            db._insert_expanded(rows)

        latest_values = mock_ev.call_args_list[1][0][2]
        assert len(latest_values) == 2  # two distinct datatypes

    def test_tsdb_insert_includes_all_rows(self, db_conn):
        """All rows (not just latest) go into the tsdb insert."""
        db, conn, _ = db_conn
        rows = [
            self._row(self.T1, 10001, 1.0),
            self._row(self.T2, 10001, 2.0),
        ]
        with patch('psycopg2.extras.execute_values') as mock_ev:
            db._insert_expanded(rows)

        # First call is the tsdb insert; it should get all rows
        tsdb_values = mock_ev.call_args_list[0][0][2]
        assert tsdb_values == rows
