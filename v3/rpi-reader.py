#!/usr/bin/env python3

# The MIT License (MIT)
#
# Copyright (c) 2020 ladyada for Adafruit Industries
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.


## This has been cut down and modified by djacobowitz. Sep 2020

"""
`adafruit_pm25`
================================================================================

Python library for PM2.5 Air Quality Sensors


* Author(s): ladyada, djacobowitz, jelson

Implementation Notes
--------------------

**Hardware:**

Works with most (any?) Plantower UART PM2.5 sensor.

**Software and Dependencies:**

* Pyserial

"""

# constants
MAX_CACHE_LEN = 15
SENSOR_PATH = "/dev/ttyS0"

# imports
from mylogging import say
import argparse
import collections
import datetime
import httpclient
import serial
import struct
import time

class PM25:
    """Super-class for generic PM2.5 sensors. Subclasses must implement
    _read_into_buffer to fill self._buffer with a packet of data"""

    def __init__(self):
        # rad, ok make our internal buffer!
        self._buffer = bytearray(32)
        self.field_names = (
            "pm10_standard",
            "pm25_standard",
            "pm100_standard",
            "pm10_env",
            "pm25_env",
            "pm100_env",
            "particles_03um",
            "particles_05um",
            "particles_10um",
            "particles_25um",
            "particles_50um",
            "particles_100um",
        )
        self.aqType = collections.namedtuple('aqdata', self.field_names)

    def getFields(self):
        return self.field_names

    def _read_into_buffer(self):
        """Low level buffer filling function, to be overridden"""
        raise NotImplementedError()

    def read(self):
        """Read any available data from the air quality sensor and
        return a dictionary with available particulate/quality data"""
        self._read_into_buffer()
        # print([hex(i) for i in self._buffer])

        # check packet header
        if (self._buffer[0] != 0x42) or (self._buffer[1] != 0x4D):
            raise RuntimeError("Invalid PM2.5 header")

        # check frame length
        frame_len = struct.unpack(">H", self._buffer[2:4])[0]
        if frame_len != 28:
            raise RuntimeError("Invalid PM2.5 frame length")

        checksum = struct.unpack(">H", self._buffer[30:32])[0]
        check = sum(self._buffer[0:30])
        if check != checksum:
            raise RuntimeError("Invalid PM2.5 checksum")

        # unpack data
        return self.aqType._asdict(
            self.aqType._make(
                struct.unpack(">HHHHHHHHHHHH", self._buffer[4:28])
            )
        )

class PM25_UART(PM25):
    """
    A driver for the PM2.5 Air quality sensor over UART
    """

    def __init__(self, uart, reset_pin=None):
        if reset_pin:
            # Reset device
            reset_pin.direction = Direction.OUTPUT
            reset_pin.value = False
            time.sleep(0.01)
            reset_pin.value = True
            # it takes at least a second to start up
            time.sleep(1)

        self._uart = uart
        super().__init__()

    def _read_into_buffer(self):
        while True:
            b = self._uart.read(1)
            if not b:
                raise RuntimeError("Unable to read from PM2.5 (no start of frame)")
            if b[0] == 0x42:
                break
        self._buffer[0] = b[0]  # first byte and start of frame

        remain = self._uart.read(31)
        if not remain or len(remain) != 31:
            raise RuntimeError("Unable to read from PM2.5 (incomplete frame)")
        for i in range(31):
            self._buffer[i + 1] = remain[i]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s", "--sensor-id",
        help="Numeric sensor ID to write to database",
        action='store',
        required='true',
    )
    parser.add_argument(
        "-u", "--url",
        help="URL to post to",
        action='store',
        required=True,
    )
    parser.add_argument(
        "-p", "--password",
        help="Password for server",
        action='store',
        required=True,
    )
    args = parser.parse_args()
    say(f"Starting; args: {args}")

    # validate sensor id
    sensorid = int(args.sensor_id)
    if sensorid <= 0:
        say("Invalid sensor ID, must be >0")
        sys.exit(1)

    db = httpclient.DataClient(args.url, args.password)

    # start reading!
    uart = serial.Serial(SENSOR_PATH, baudrate=9600, timeout=2)
    pm25 = PM25_UART(uart)
    cache = []
    while True:
        data = pm25.read()
        cache.append({
            'time': datetime.datetime.now(),
            'pm1.0': data['pm10_standard'],
            'pm2.5': data['pm25_standard'],
            'pm10.0': data['pm100_standard'],
        })

        # post data to server if needed
        if len(cache) >= MAX_CACHE_LEN:
            try:
                db.insert_batch(sensorid, cache)
                cache.clear()
            except Exception as e:
                say(f"Could not post sensor data: {e}")

main()
