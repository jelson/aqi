"""
Unit tests for v3/server/netreceiver.py (SensorDataHandler)

Covers: HMAC and cleartext authentication, data ingestion, timestamp
conversion, D-Bus notification, MAC address lookup, and the recent-lookups log.
"""

import datetime
import hashlib
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from netreceiver import SensorDataHandler

# ── Helpers ──────────────────────────────────────────────────────────────────

PASSWORD = 'testpassword'
SENSOR = 'jer-office'
SENSORDATA = [{'time': 1_000_000.0, 'pm1.0': 1.0, 'pm2.5': 5.0, 'pm10.0': 10.0}]


def make_handler(password=PASSWORD, dbus_notify=False):
    """Create a SensorDataHandler with mocked DB and D-Bus."""
    config = {'password': password, 'dbus-notify': dbus_notify}
    mock_db = MagicMock()
    mock_bus = MagicMock()
    with patch('pms5003db.PMS5003Database', return_value=mock_db), \
         patch('dbus.SystemBus', return_value=mock_bus):
        handler = SensorDataHandler(config)
    return handler, mock_db, mock_bus


def make_hmac_payload(password=PASSWORD, sensorname=SENSOR, sensordata=None):
    """Build a correctly HMAC-authenticated payload dict."""
    if sensordata is None:
        sensordata = list(SENSORDATA)
    salt = 'TESTSALTABCDEFGHIJKL'
    digest = hashlib.sha256(salt.encode('utf-8'))
    digest.update(password.encode('utf-8'))
    return {
        'salt': salt,
        'auth': digest.digest().hex(),
        'sensorname': sensorname,
        'sensordata': sensordata,
    }


def call_data(handler, payload_dict=None, raw_body=None):
    """
    Call handler.data() with either a dict payload or raw bytes body.
    Returns the response status set by the handler (None means success —
    the handler never sets status on a 200 response).
    """
    if raw_body is None:
        raw_body = json.dumps(payload_dict).encode('utf-8')

    mock_response = MagicMock()
    mock_response.status = None

    with patch('cherrypy.request') as mock_request, \
         patch('cherrypy.response', mock_response):
        mock_request.remote.ip = '127.0.0.1'
        mock_request.remote.port = 12345
        mock_request.headers = MagicMock()
        mock_request.headers.get.return_value = 'test-agent'
        mock_request.body.read.return_value = raw_body
        handler.data()

    return mock_response.status


def call_mac_lookup(handler, macaddr):
    """Call handler.mac_lookup() and return (result, response_status)."""
    mock_response = MagicMock()
    mock_response.status = None
    with patch('cherrypy.response', mock_response):
        result = handler.mac_lookup(macaddr)
    return result, mock_response.status


# ── Authentication ────────────────────────────────────────────────────────────

class TestAuthentication:
    def test_valid_hmac_succeeds(self):
        handler, mock_db, _ = make_handler()
        status = call_data(handler, make_hmac_payload())
        assert status is None  # no error status set
        mock_db.insert_batch.assert_called_once()

    def test_wrong_password_hmac_returns_403(self):
        handler, mock_db, _ = make_handler()
        status = call_data(handler, make_hmac_payload(password='wrongpassword'))
        assert status == 403
        mock_db.insert_batch.assert_not_called()

    def test_valid_cleartext_succeeds(self):
        handler, mock_db, _ = make_handler()
        payload = {
            'clowny-cleartext-password': PASSWORD,
            'sensorname': SENSOR,
            'sensordata': list(SENSORDATA),
        }
        status = call_data(handler, payload)
        assert status is None
        mock_db.insert_batch.assert_called_once()

    def test_wrong_cleartext_returns_403(self):
        handler, mock_db, _ = make_handler()
        payload = {
            'clowny-cleartext-password': 'wrongpassword',
            'sensorname': SENSOR,
            'sensordata': list(SENSORDATA),
        }
        status = call_data(handler, payload)
        assert status == 403
        mock_db.insert_batch.assert_not_called()

    def test_no_auth_returns_403(self):
        handler, mock_db, _ = make_handler()
        payload = {'sensorname': SENSOR, 'sensordata': list(SENSORDATA)}
        status = call_data(handler, payload)
        assert status == 403
        mock_db.insert_batch.assert_not_called()

    def test_salt_without_auth_key_falls_to_no_auth_403(self):
        """Having 'salt' but no 'auth' key is treated as no auth provided."""
        handler, mock_db, _ = make_handler()
        payload = {
            'salt': 'SOMESALT',
            # 'auth' key intentionally absent
            'sensorname': SENSOR,
            'sensordata': list(SENSORDATA),
        }
        status = call_data(handler, payload)
        assert status == 403
        mock_db.insert_batch.assert_not_called()


# ── Data endpoint behaviour ───────────────────────────────────────────────────

class TestDataEndpoint:
    def test_invalid_json_returns_400(self):
        handler, mock_db, _ = make_handler()
        status = call_data(handler, raw_body=b'not valid json {')
        assert status == 400
        mock_db.insert_batch.assert_not_called()

    def test_empty_body_returns_400(self):
        handler, mock_db, _ = make_handler()
        status = call_data(handler, raw_body=b'')
        assert status == 400
        mock_db.insert_batch.assert_not_called()

    def test_unix_timestamps_converted_to_datetime(self):
        """Sensor record timestamps (unix floats) become datetime objects."""
        handler, mock_db, _ = make_handler()
        ts = 1_000_000.0
        payload = make_hmac_payload(sensordata=[{'time': ts, 'pm2.5': 5.0}])
        call_data(handler, payload)

        sensordata_arg = mock_db.insert_batch.call_args[0][2]
        assert isinstance(sensordata_arg[0]['time'], datetime.datetime)
        assert sensordata_arg[0]['time'] == datetime.datetime.fromtimestamp(ts)

    def test_sensorname_forwarded_to_insert_batch(self):
        handler, mock_db, _ = make_handler()
        call_data(handler, make_hmac_payload(sensorname='jer-bedroom'))
        assert mock_db.insert_batch.call_args[0][0] == 'jer-bedroom'

    def test_insert_batch_exception_propagates_as_500(self):
        """Exceptions from insert_batch are not swallowed (become HTTP 500)."""
        handler, mock_db, _ = make_handler()
        mock_db.insert_batch.side_effect = Exception("unknown sensor name")
        with pytest.raises(Exception, match="unknown sensor name"):
            call_data(handler, make_hmac_payload())


# ── D-Bus notification ────────────────────────────────────────────────────────

class TestDBusNotification:
    def test_signal_sent_when_enabled(self):
        handler, mock_db, mock_bus = make_handler(dbus_notify=True)
        call_data(handler, make_hmac_payload(sensorname=SENSOR))
        mock_bus.send_message.assert_called_once()

    def test_signal_not_sent_when_disabled(self):
        handler, mock_db, mock_bus = make_handler(dbus_notify=False)
        call_data(handler, make_hmac_payload())
        mock_bus.send_message.assert_not_called()

    def test_dbus_error_does_not_fail_request(self):
        """A D-Bus send failure is caught; the HTTP request still succeeds."""
        handler, mock_db, mock_bus = make_handler(dbus_notify=True)
        mock_bus.send_message.side_effect = Exception("dbus exploded")
        status = call_data(handler, make_hmac_payload())
        assert status is None  # request still succeeds

    def test_signal_carries_sensorname(self):
        """The D-Bus signal message is constructed before send_message is called."""
        handler, mock_db, mock_bus = make_handler(dbus_notify=True)
        call_data(handler, make_hmac_payload(sensorname='jer-bedroom'))
        # send_message was called with exactly one positional arg (the message object)
        assert mock_bus.send_message.call_count == 1
        sent_msg = mock_bus.send_message.call_args[0][0]
        assert sent_msg is not None

    def test_send_message_serialized_by_lock(self):
        """Concurrent requests must not call send_message simultaneously."""
        import threading as _threading
        handler, mock_db, mock_bus = make_handler(dbus_notify=True)

        call_order = []
        lock_held_during_send = []

        original_send = mock_bus.send_message.side_effect

        def tracked_send(msg):
            # Record whether the lock is held (it should be — we're inside 'with dbus_lock')
            lock_held_during_send.append(not handler.dbus_lock.acquire(blocking=False))
            if not lock_held_during_send[-1]:
                handler.dbus_lock.release()  # clean up if we accidentally acquired it

        mock_bus.send_message.side_effect = tracked_send

        threads = [
            _threading.Thread(target=call_data, args=(handler, make_hmac_payload()))
            for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert mock_bus.send_message.call_count == 5
        # The lock must have been held every time send_message was called
        assert all(lock_held_during_send)


# ── MAC address lookup ────────────────────────────────────────────────────────

class TestMacLookup:
    def _setup_cursor(self, mock_db, fetchone_result):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = fetchone_result
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_db.get_raw_db.return_value = mock_conn
        return mock_conn, mock_cursor

    def test_known_mac_returns_sensor_name(self):
        handler, mock_db, _ = make_handler()
        self._setup_cursor(mock_db, ('jer-office',))
        result, status = call_mac_lookup(handler, 'aa:bb:cc:dd:ee:ff')
        assert result == 'jer-office'
        assert status is None

    def test_unknown_mac_returns_none_and_401(self):
        handler, mock_db, _ = make_handler()
        self._setup_cursor(mock_db, None)
        result, status = call_mac_lookup(handler, 'ff:ff:ff:ff:ff:ff')
        assert result is None
        assert status == 401

    def test_rollback_called_after_lookup(self):
        handler, mock_db, _ = make_handler()
        mock_conn, _ = self._setup_cursor(mock_db, ('jer-office',))
        call_mac_lookup(handler, 'aa:bb:cc:dd:ee:ff')
        mock_conn.rollback.assert_called_once()

    def test_lookup_logged_to_recent_lookups(self):
        handler, mock_db, _ = make_handler()
        self._setup_cursor(mock_db, ('jer-office',))
        call_mac_lookup(handler, 'aa:bb:cc:dd:ee:ff')
        log_content = handler.recent_lookups()
        assert 'aa:bb:cc:dd:ee:ff' in log_content
        assert 'jer-office' in log_content


# ── Recent lookups log ────────────────────────────────────────────────────────

class TestRecentLookups:
    def test_initially_empty(self):
        handler, _, _ = make_handler()
        assert handler.recent_lookups() == ''

    def test_reflects_written_content(self):
        handler, _, _ = make_handler()
        handler.lookup_log.write('<p>test entry one\n')
        handler.lookup_log.flush()
        assert 'test entry one' in handler.recent_lookups()

    def test_accumulates_multiple_entries(self):
        handler, _, _ = make_handler()
        handler.lookup_log.write('<p>entry one\n')
        handler.lookup_log.write('<p>entry two\n')
        handler.lookup_log.flush()
        content = handler.recent_lookups()
        assert 'entry one' in content
        assert 'entry two' in content
