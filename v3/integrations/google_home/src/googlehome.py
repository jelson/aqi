"""
Google Smart Home integration for air quality sensors.

This service implements a Google Smart Home Cloud-to-Cloud integration
that exposes air quality sensors as smart home devices. Users can query
sensors by voice:

  "Hey Google, what's the bedroom air quality?"
  "Hey Google, what's the PM2.5 in the office?"

The integration implements:
- SYNC intent: Lists available sensors and their capabilities
- QUERY intent: Returns current sensor readings
- EXECUTE intent: Not used (sensors are read-only)
- DISCONNECT intent: Handles account unlinking

See: https://developers.home.google.com/cloud-to-cloud
"""

import cherrypy
import json
import os
import sys

# project libraries
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from common.mylogging import say
from server.pms5003db import PMS5003Database
from integrations.google_home.src.oauth import OAuthHandler


class GoogleSmartHomeIntegration:
    """Smart Home integration for air quality sensors."""

    def __init__(self, config):
        self.config = config
        self.pmsdb = PMS5003Database()

        # Initialize OAuth handler
        self.oauth = OAuthHandler(config)

        # Map friendly names to sensor names - REQUIRED
        room_mapping = config.get('room_mapping')
        if not room_mapping:
            raise ValueError("room_mapping is required in config file")
        # Validate room_mapping is a dictionary
        if not isinstance(room_mapping, dict):
            raise ValueError("room_mapping in config must be a dictionary")
        if len(room_mapping) == 0:
            raise ValueError(
                "room_mapping must contain at least one room"
            )
        self.room_mapping = room_mapping

    # ========================================================================
    # OAuth Endpoints (delegated to OAuth handler)
    # ========================================================================

    @cherrypy.expose
    def auth(self, **kwargs):
        """OAuth authorization endpoint (delegated to OAuth handler)."""
        return self.oauth.auth(**kwargs)

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def token(self, **kwargs):
        """OAuth token endpoint (delegated to OAuth handler)."""
        return self.oauth.token(**kwargs)

    # ========================================================================
    # Sensor Data Access
    # ========================================================================

    def get_trailing_average(self, sensorname, averaging_sec=60):
        """
        Get the trailing average AQI for a sensor over the last N seconds.

        Args:
            sensorname: Name of the sensor
            averaging_sec: Number of seconds to average over (default: 60)

        Returns:
            Rounded AQI value, or None if no data available or on error
        """
        say(f"get_trailing_average: START for sensor={sensorname}")
        try:
            sensorid = self.pmsdb.get_sensorid_by_name(sensorname)
            if not sensorid:
                say(f"Unknown sensor name: {sensorname}")
                return None
            say(f"get_trailing_average: sensorid={sensorid}")

            datatype = self.pmsdb.get_datatype_by_name('aqi2.5')
            if not datatype:
                say("ERROR: 'aqi2.5' datatype not found in database")
                return None
            say(f"get_trailing_average: datatype={datatype}")

            db = self.pmsdb.get_raw_db()
            cursor = db.cursor()
            say("get_trailing_average: executing query...")

            cursor.execute(
                """
                SELECT avg("value")
                FROM sensordatav4_tsdb
                WHERE
                    sensorid=%s AND
                    datatype=%s AND
                    time > now() - make_interval(secs => %s)
                """,
                (sensorid, datatype, averaging_sec)
            )

            say("get_trailing_average: fetching result...")
            row = cursor.fetchone()
            db.commit()

            avg_value = row[0]
            say(f"get_trailing_average: avg_value={avg_value}")

            if avg_value is None:
                return None

            result = round(avg_value)
            say(f"get_trailing_average: COMPLETE, returning {result}")
            return result
        except Exception as e:
            say(f"Database error getting AQI for {sensorname}: {e}")
            return None

    # ========================================================================
    # Smart Home Intents
    # ========================================================================

    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def serve(self):
        """
        Main Smart Home fulfillment endpoint.

        Handles SYNC, QUERY, EXECUTE, and DISCONNECT intents.
        """
        request_data = cherrypy.request.json

        # Verify authorization using OAuth handler
        auth_header = cherrypy.request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            cherrypy.response.status = 401
            return {"error": "Missing authorization"}

        access_token = auth_header[7:]  # Remove 'Bearer ' prefix
        username = self.oauth.verify_access_token(access_token)

        if not username:
            cherrypy.response.status = 401
            return {"error": "Invalid or expired token"}

        say(f"Smart Home request from {username}: "
            f"{json.dumps(request_data, indent=2)}")

        # Route to appropriate intent handler
        request_id = request_data.get('requestId')
        inputs = request_data.get('inputs', [])

        if not inputs:
            cherrypy.response.status = 400
            return {"error": "No inputs provided"}

        intent = inputs[0].get('intent')

        # Validate intent is not None
        if not intent:
            cherrypy.response.status = 400
            return {"error": "Missing intent in request"}

        if intent == 'action.devices.SYNC':
            return self.handle_sync(request_id)
        elif intent == 'action.devices.QUERY':
            return self.handle_query(request_id, inputs[0])
        elif intent == 'action.devices.EXECUTE':
            return self.handle_execute(request_id, inputs[0])
        elif intent == 'action.devices.DISCONNECT':
            return self.handle_disconnect(request_id)
        else:
            cherrypy.response.status = 400
            return {"error": f"Unknown intent: {intent}"}

    def handle_sync(self, request_id):
        """
        Handle SYNC intent - return list of available sensors.

        Args:
            request_id: Request ID from Google

        Returns:
            SYNC response with device list
        """
        devices = []

        for friendly_name, sensor_name in self.room_mapping.items():
            device_id = f"aqi-sensor-{sensor_name}"

            devices.append({
                "id": device_id,
                "type": "action.devices.types.SENSOR",
                "traits": [
                    "action.devices.traits.SensorState"
                ],
                "name": {
                    "defaultNames": ["AQI Sensor"],
                    "name": f"{friendly_name.title()} Air Quality",
                    "nicknames": [
                        friendly_name,
                        f"{friendly_name} AQI",
                        f"{friendly_name} air quality"
                    ]
                },
                "willReportState": False,
                "roomHint": friendly_name.title(),
                "deviceInfo": {
                    "manufacturer": "DIY",
                    "model": "PMS5003",
                    "hwVersion": "1.0",
                    "swVersion": "1.0"
                },
                "attributes": {
                    "sensorStatesSupported": [
                        {
                            "name": "AirQuality",
                            "numericCapabilities": {
                                "rawValueUnit": "AQI"
                            }
                        },
                        {
                            "name": "PM2.5",
                            "numericCapabilities": {
                                "rawValueUnit": "MICROGRAMS_PER_CUBIC_METER"
                            }
                        }
                    ]
                }
            })

        response = {
            "requestId": request_id,
            "payload": {
                "agentUserId": self.oauth.username,
                "devices": devices
            }
        }

        say(f"SYNC response: {len(devices)} devices")
        return response

    def handle_query(self, request_id, input_data):
        """
        Handle QUERY intent - return current sensor states.

        Args:
            request_id: Request ID from Google
            input_data: Input data containing device list

        Returns:
            QUERY response with device states
        """
        devices = input_data.get('payload', {}).get('devices', [])
        device_states = {}

        for device in devices:
            device_id = device.get('id')

            # Validate device_id is not None
            if not device_id:
                continue

            # Extract sensor name from device ID
            if not device_id.startswith('aqi-sensor-'):
                continue

            sensor_name = device_id[len('aqi-sensor-'):]

            # Get current AQI
            aqi = self.get_trailing_average(sensor_name)

            if aqi is None:
                # Sensor offline or no recent data
                device_states[device_id] = {
                    "online": False,
                    "status": "OFFLINE"
                }
            else:
                # Return sensor state
                device_states[device_id] = {
                    "online": True,
                    "status": "SUCCESS",
                    "currentSensorStateData": [
                        {
                            "name": "AirQuality",
                            "rawValue": aqi
                        }
                    ]
                }

        response = {
            "requestId": request_id,
            "payload": {
                "devices": device_states
            }
        }

        say(f"QUERY response: {len(device_states)} devices")
        return response

    def handle_execute(self, request_id, input_data):
        """
        Handle EXECUTE intent - not used for read-only sensors.

        Args:
            request_id: Request ID from Google
            input_data: Input data containing commands

        Returns:
            EXECUTE response with error (sensors are read-only)
        """
        commands = input_data.get('payload', {}).get('commands', [])
        command_results = []

        for command in commands:
            devices = command.get('devices', [])
            for device in devices:
                command_results.append({
                    "ids": [device.get('id')],
                    "status": "ERROR",
                    "errorCode": "functionNotSupported"
                })

        response = {
            "requestId": request_id,
            "payload": {
                "commands": command_results
            }
        }

        return response

    def handle_disconnect(self, request_id):
        """
        Handle DISCONNECT intent - revoke all tokens for this user.

        Args:
            request_id: Request ID from Google

        Returns:
            DISCONNECT response
        """
        # In a production system, you'd revoke tokens for the specific user
        # For this simple implementation, we just return success
        say("DISCONNECT request received")

        return {
            "requestId": request_id,
            "payload": {}
        }
