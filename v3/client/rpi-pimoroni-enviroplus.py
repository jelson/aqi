#!/usr/bin/env python3

"""

Read the various sensors of the Pimoroni Enviro+ shield, including
the PMS5003 particulate sensor.

   Shield info here:
      https://shop.pimoroni.com/products/enviro?variant=31155658489939

This script assumes that you have already *installed* all of Pimoroni's
python library and helpers, found here:

      https://github.com/pimoroni/enviroplus-python/

Be sure to read their readme, since their "installation" is a bit
wonky.

"""

# constants
PM25_PATH = "/dev/ttyAMA0"

# system imports

import argparse, collections, datetime, json, os
import re, serial, struct, sys, time

# display libraries
import ST7735
from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
import fonts.ttf

# sensor libraries
try:
    import smbus2 as smbus
except:
    import smbus

import bme280
import ltr559

import enviroplus.gas

# project libraries
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import httpclient
import datacache
from common.mylogging import say

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


class Screen():
    def __init__(self):
        self.lcd = ST7735.ST7735(
            port=0,
            cs=1,
            dc=9,
            backlight=12,
            rotation=270,
            spi_speed_hz=10000000
        )
        self.lcd.begin()
        self.img = Image.new('RGB', (self.lcd.width, self.lcd.height), color=(0,0,0))
        self.draw = ImageDraw.Draw(self.img)
        self.font = ImageFont.truetype(fonts.ttf.RobotoMedium, 14)

    def textXY(self, loc, color, text):
        self.draw.text(loc, text, font=self.font, fill=color)
    def clear(self):
        self.draw.rectangle((0, 0, self.lcd.width, self.lcd.height), (0,0,0))
    def show(self):
        self.lcd.display(self.img)


class ScreenReport():
    def __init__(self, screen):
        self.screen = screen
        self.status = '__na'
        self.count = 0

    def set_status(self,s):
        self.status = s

    def get_status(self):
        return self.status

    def showData(self, d):
        keys = list(d.keys())
        key  = keys[self.count % len(keys)]
        self.screen.clear()
        if key is not 'time':
            self.screen.textXY((0,0), (255,255,0), f'{key}: ')
            value = d[key]
            self.screen.textXY((10,20), (255,0,255), f'{value:0.2f}')
        ts = re.match(r'(.+?)(?=\.)', d['time'].isoformat())[1]
        self.screen.textXY((0,40), (0,255,255), ts)
        self.screen.textXY((0,60), (0,255,0), self.get_status())
        self.screen.show()
        self.count += 1


def main():
    parser = argparse.ArgumentParser()
    httpclient.build_parser(parser)
    args = parser.parse_args()
    say(f"Starting; args: {args}")

    # set up the cache and the thread that services it
    cache = datacache.DataCache(args)

    # initialize sensor objects
    say(f"Opening {PM25_PATH}")
    uart = serial.Serial(PM25_PATH, baudrate=9600, timeout=2)
    pm25 = PM25_UART(uart)

    say(f'Openining bme280 device')
    bus = smbus.SMBus(1)
    tsensor = bme280.BME280(i2c_dev=bus)
    lsensor = ltr559.LTR559()

    screen = Screen()
    sr= ScreenReport(screen)

    def show_res(rv):
        descr = 'Post OK' if rv.status_code == 200 else 'Post FAIL'
        sr.set_status(f'{descr}/{rv.status_code}')

    cache.set_send_callback(show_res)

    while True:
        pm_data = pm25.read()
        gas_data = enviroplus.gas.read_all()

        new_sample = {
            'time': datetime.datetime.now(),
            'pm1.0': pm_data['pm10_standard'],
            'pm2.5': pm_data['pm25_standard'],
            'pm10.0': pm_data['pm100_standard'],
            'temperature_C': tsensor.get_temperature(),
            'humidity_perc': tsensor.get_humidity(),
            'pressure_hPa':  tsensor.get_pressure(),
            'brightness_lux': lsensor.get_lux(),
            'oxidizing_ohms': gas_data.oxidising,
            'reducing_ohms': gas_data.reducing,
            'nh3_ohms': gas_data.nh3,
        }

        sr.showData(new_sample)

        if True:
            cache.append(new_sample)


if __name__ == '__main__':
    main()
