# DIY Air Quality Sensor with Wireless Logging

This is the software for a do-it-yourself air quality sensor system based on the
Plantower PMS5003 particulate sensor, which senses PM1.0, PM2.5 and PM10.0
particulates. Each sensor is connected to a Raspberry Pi Zero W, which
periodically transmits data wirelessly to a small web server. Any number of
sensors are supported. All data is written to a Postgres database, which can be
easily visualized with tools such as Grafana. Also included is a [3D printable
case](https://www.thingiverse.com/thing:4940995) I designed to fit the Pi and
sensor.

![Pi and sensor in case](docs/case-open.jpg)
![Case with cover](docs/case-closed.jpg)
![Grafana UI](docs/grafana-screencap.png)

## Credits

The PMS5003 parsing code is based on
[Adafruit's](https://learn.adafruit.com/pm25-air-quality-sensor) and
[dgj's](https://github.com/djacobow/airmon) code.

## Hardware

* Buy a PMS5003 sensor. They're sold under various brand names on various sites
  including [Adafruit](https://www.adafruit.com/product/3686) /
  [Mouser](https://www.mouser.com/ProductDetail/Adafruit/3686),
  [Amazon](https://www.amazon.com/gp/product/B092H9FSC9),
  [BangGood](https://usa.banggood.com/PMS5003-PM2_5-Air-Particle-Dust-Sensor-Laser-Digital-Output-Module-High-Precision-Air-Haze-Detection-Smart-Home-Device-p-1553818.html),
  [AliExpress](https://www.aliexpress.com/item/1005001793669306.html), [eBay](https://www.ebay.com/sch/i.html?_from=R40&_trksid=p2047675.m570.l1313&_nkw=pms5003&_sacat=0)...

* Buy a [Raspberry Pi Zero W](https://www.raspberrypi.org/products/raspberry-pi-zero-w/) (the WiFi variant) without headers

* Solder 3 wires from the PMS5003 to the Raspberry Pi. For reference, see the
  diagrams of the [sensor pinout](https://github.com/jelson/aqi/blob/main/docs/pms5003_pinout.png) and [Pi pinout](https://pinout.xyz/).
   * Sensor Pin 1 (VCC) to Pi Pin 4 (5V Power)

   * Sensor Pin 2 (GND) to Pi Pin 6 (GND)

   * Sensor Pin 5 (TXD) to Pi Pin 10 (Serial port RX)

* Optional: 3D print the [case I designed](https://www.thingiverse.com/thing:4940995).
  Attach the Pi to the case's integrated standoffs using 4xM2.5
  machine screws. The cover also attaches to the case using 4xM2.5 screws.

## Software

* Configure the server that receives the data:

    * Install Postgres on your server. Use a SQL script similar to [this
      example](https://github.com/jelson/aqi/blob/main/v3/server/create-table.sql)
      to create a database and table.

    * Install the receiver service's prereqs on your server: python modules `aqi`
      and `cherrypy`

    * Create a configuration file for the receiver service specifying a password of
      your choice. If you want to use HTTPS (TLS), also specify the path to your
      HTTPS certficate, key, and cert chain.  An example config file can be found
      [here](https://github.com/jelson/aqi/blob/main/v3/server/netreceiver-config-example.yml).

      If you'd rather not use HTTPS, leave the certificate configuration lines out
      of the receiver configuration file. The server will start as HTTP instead of
      HTTPS. If you do this, make sure you use http:// URLs instead of https:// with
      the client tools.

    * Run the receiver service using a command line like `v3/server/netreceiver.py --config
      /path/to/config-file.yml`. You may wish to use `systemd` to have the service start
      automatically; an example systemd config file is
      [here](https://github.com/jelson/aqi/blob/main/v3/server/netreceiver.service).

    * Test the receiver. Note that by default it runs on port 15000. Run the unit
      test with a command like
       ```
       aqi/v3/test/sendtest.py --url https://your-server:15000/data/ -s 1000 -n 10 -p 'password-you-picked'
       ```
       The return value should be `True`, indicating success. Check the database
       table and ensure it has been populated with 10 rows of data (or whatever
       value you passed to `-n`) tagged with sensor ID 1000 (or whatever value you
       passed to `-s`). A 403 result indicates there was a mismatch between the
       password you passed to sendtest.py and the one in the receiver's
       configuration file.

* Configure each of your RPi sensors:

   * Install the [Raspberry Pi OS](https://www.raspberrypi.org/software/),
     configure WiFi, enable ssh

   * Boot the Pi into your new image, connect to it via ssh (or the console).
     Run `raspi-config` to configure the serial port to be usable for an
     external peripheral rather than a console.

   * Use `apt-get` to install `git`, `python3` and `python3-serial` . Use `git
     clone` to clone this repository into the `pi` user's home directory.

   * Try running the sensor reader:
       ```
       /home/pi/aqi/v3/client/rpi-reader.py -v --url https://your-server:15000/data/ -s 1 -p 'password-you-picked'
       ```
     The `-v` (verbose) argument tells the client to print sensor data as it
     arrives from the serial port; you should see a record about once every
     second. After 15 seconds it should try to push data to your server. `-s 1`
     means Sensor 1; if you have more than one sensor, give each a unique
     number.

   * If it works, arrange to have the Pi start rpi-reader.py automatically on
     each boot by adding it to systemd; an example config file is
     [here](https://github.com/jelson/aqi/blob/main/v3/client/rpi-reader.service). For example:

     * `cp aqi/v3/client/rpi-reader.service /etc/systemd/system`

     * `vi /etc/systemd/system/rpi-reader.service` (customize with your server URL and password)

     * `systemctl daemon-reload`

     * `systemctl start rpi-reader.service`

   * Check `journalctl -f` to look for log messages. You should see `rpi-reader`
     reporting that it is sending data to your server every 15 seconds.

* Optional: install Grafana (or similar tool) to visualize the data from your
  database.

## Google Home Integration

You can query your air quality data using Google Home / Google Assistant with
voice commands like "Hey Google, what's the bedroom air quality?" or "Hey
Google, what's the PM2.5 in the office?" This integration uses Google's Smart
Home Actions (Cloud-to-Cloud) to expose your sensors as smart home devices.

### Setup Steps

#### 1. Install and Configure the Integration Service

Create a config file somewhere outside the repository so key material and
passwords aren't checked into github:

```bash
# Copy the example config to a secure location
cp v3/integrations/google_home/config/config-example.yml /path/to/your/google-home-smarthome-config.yml

# Generate a random OAuth client secret
openssl rand -hex 32
```

Edit the configuration:
- **oauth_client_id**: Can leave as default (`aqi-sensors`) or customize
- **oauth_client_secret**: Paste the random secret from the `openssl rand -hex 32` command above
- **google_oauth_client_id**: OAuth client ID from Google Cloud Console (see step 2a below)
- **google_oauth_client_secret**: OAuth client secret from Google Cloud Console
- **users**: Map Google email addresses to their sensor mappings. Each user should have a `room_mapping` dictionary that maps friendly names to sensor names in the database

Example:
```yaml
users:
  your-email@gmail.com:
    room_mapping:
      bedroom: your-sensor-bedroom
      office: your-sensor-office
```

Test the database query (before starting the service):

```bash
# Test that the service can query your sensors
v3/integrations/google_home/src/main.py --config /path/to/your/google-home-smarthome-config.yml --test-query jer-bedroom
```

If it works, set up systemd for auto-start:

```bash
cp v3/integrations/google_home/google-home-smarthome.service /etc/systemd/system/
vi /etc/systemd/system/google-home-smarthome.service  # customize binary and config path
systemctl daemon-reload
systemctl start google-home-smarthome.service
systemctl enable google-home-smarthome.service
```

Set up reverse proxy (e.g. Apache or nginx). Note HTTPS must be configured with
a valid cert.

**Apache** (add to your VirtualHost configuration):
```apache
<Location /smarthome>
    # Forward all /smarthome/* requests to the local service
    ProxyPass http://127.0.0.1:15001
    ProxyPassReverse http://127.0.0.1:15001

    # Required headers for reverse proxy support
    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-Host "%{HTTP_HOST}s"
    RequestHeader set X-Forwarded-Prefix "/smarthome"
</Location>
```

**nginx**:
```nginx
location /smarthome/ {
    proxy_pass http://127.0.0.1:15001/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Prefix /smarthome;
}
```

Test that the endpoints are accessible via HTTPS:
```bash
# Should return a redirect to Google OAuth, not a connection error
curl -X GET 'https://your-domain.com/smarthome/auth?client_id=aqi-sensors&redirect_uri=https://oauth-redirect.googleusercontent.com/r/YOUR_PROJECT_ID&state=test&response_type=code'

# Should return a 400 error (missing POST data), not a connection error
curl -X POST https://your-domain.com/smarthome/auth/token
```

#### 2. Create Google OAuth 2.0 Credentials

The integration uses "Sign in with Google" for user authentication. You need to create OAuth 2.0 credentials:

1. **Go to Google Cloud Console**
   - Visit [console.cloud.google.com](https://console.cloud.google.com/)
   - Create a new project or select an existing one

2. **Enable the Google+ API** (required for OAuth)
   - In the left sidebar, go to **APIs & Services** → **Library**
   - Search for "Google+ API"
   - Click on it and press **Enable**

3. **Create OAuth 2.0 credentials**
   - In the left sidebar, go to **APIs & Services** → **Credentials**
   - Click **"Create Credentials"** → **"OAuth client ID"**
   - If prompted, configure the OAuth consent screen first:
     - User type: **External**
     - App name: Your choice (e.g., "AQI Sensors")
     - User support email: Your email
     - Developer contact: Your email
     - Click **"Save and Continue"** through the rest
   - Application type: **Web application**
   - Name: "AQI Smart Home Integration"
   - **Authorized redirect URIs**: Add `https://your-domain.com/smarthome/auth/callback`
   - Click **"Create"**

4. **Copy credentials to config file**
   - Copy the **Client ID** to `google_oauth_client_id` in your config
   - Copy the **Client secret** to `google_oauth_client_secret` in your config

#### 3. Create a Smart Home Action in Google Home Developer Console

1. **Go to the Google Home Developer Console**
   - Visit [console.home.google.com](https://console.home.google.com/)
   - Sign in with your Google account

2. **Create a new project**
   - Click **"New project"** button
   - Enter a project name (e.g., "AQI Sensors")
   - Click **"Create project"**

3. **Set up Cloud-to-cloud integration**
   - You'll be taken to the project dashboard
   - In the left sidebar, click **"Develop"**
   - Click **"Cloud-to-cloud"** card
   - Click **"Add"** button to create a new integration

4. **Configure integration basics**
   - **Name**: Enter "AQI Sensors" (or your preferred name - this
     appears in Google Home app)
   - **Device type**: Select **"Sensor"**
   - **Logo**: Upload an icon file (required - use the provided
     [icon.png](v3/integrations/google_home/assets/icon.png) or create
     your own)
   - Click **"Next"**

5. **Configure Account Linking (OAuth)**
   - **Linking type**: Select **"OAuth"** / **"Authorization Code"**
   - **Client ID**: Enter the value from your config file's
     `oauth_client_id` (default: `aqi-sensors`)
   - **Client secret**: Enter the value you generated with
     `openssl rand -hex 32`
   - **Authorization URL**: `https://your-domain.com/smarthome/auth`
   - **Token URL**: `https://your-domain.com/smarthome/auth/token`
   - **Scopes**: Leave empty or add any dummy scope (not used by this
     integration)
   - Click **"Next"**

6. **Configure the Fulfillment endpoint**
   - **Fulfillment URL**: `https://your-domain.com/smarthome/serve`
   - Click **"Save"**

7. **Enable testing**
   - In the left sidebar, click **"Test"**
   - Click **"Start testing"** button
   - Your integration is now available for testing on devices linked to
     your Google account

#### 4. Link Your Account in Google Home App

1. Open the Google Home app on your phone
2. Tap "+" (Add) → "Set up device" → "Works with Google"
3. Search for your project name (e.g., "AQI Sensors")
4. Tap it and you'll be redirected to Google Sign-In
5. Sign in with a Google account that's listed in your config file's `users` section
6. Grant permission to the integration
7. Google will discover your sensors

You should now see sensors like "Bedroom Air Quality" and "Office Air
Quality" in the account linking confirmation (though they won't appear in
the main Google Home interface - this is normal for sensors).

#### 5. Try Voice Queries

Say to any Google Home device or Google Assistant:
- **"Hey Google, what's the bedroom air quality?"**
- **"Hey Google, what's the office air quality?"**

Google will query your sensors and speak responses like:
- "The bedroom air quality is 23 AQI"
- "The office air quality is 15 AQI"

### How It Works

The integration exposes each room's sensor as a Smart Home SENSOR device with
the SensorState trait. When you ask about air quality, Google sends a QUERY
intent to the `/smarthome/serve` endpoint. The AQI service queries Postgres
for the latest sensor readings from that sensor and returns them.

### Troubleshooting

**"Could not reach [service name]" error during account linking:**

This error occurs when the OAuth token exchange fails. To diagnose:

1. Check that the service is running:
   ```bash
   systemctl status google-home-smarthome.service
   ```

2. Watch the logs in real-time during account linking:
   ```bash
   journalctl -u google-home-smarthome.service -f
   ```

3. Test the OAuth endpoints manually:
   ```bash
   # Test the auth endpoint (should return 400 "Missing required
   # OAuth parameters")
   curl -X GET https://your-domain.com/smarthome/auth

   # Test the token endpoint (should return JSON with
   # "invalid_client" error)
   curl -X POST https://your-domain.com/smarthome/auth/token \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "client_id=test&client_secret=test&grant_type=authorization_code&code=test"
   ```

4. Common causes:
   - **Reverse proxy misconfiguration**: Verify Apache/nginx is
     forwarding `/smarthome/*` to `http://127.0.0.1:15001/` and sending
     the required headers (`X-Forwarded-Proto`, `X-Forwarded-Host`,
     `X-Forwarded-Prefix`)
   - **OAuth credentials mismatch**: Ensure `oauth_client_id` and
     `oauth_client_secret` in your config file exactly match what you
     entered in the Google Home Developer Console
   - **Service not binding to correct port**: Check the logs confirm
     it's listening on the configured port (default: 15001)

**Sensors not discovered after successful account linking:**
- Check that the service is running and accessible via HTTPS
- Verify the fulfillment URL is correct in Google Console:
  `https://your-domain.com/smarthome/serve`
- Check logs for SYNC intent:
  `journalctl -u google-home-smarthome.service -f`
- Verify room_mapping in config file matches your sensor names in the
  database
