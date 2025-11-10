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

    # Mapping from database datatype names to Google Home sensor names
    DATATYPE_TO_GOOGLE = {
        'aqi2.5': 'AirQuality',
        'pm1.0': 'PM1',
        'pm2.5': 'PM2.5',
        'pm10.0': 'PM10',
        'temperature': 'AmbientTemperature',
        'humidity': 'AmbientHumidity'
    }

    @staticmethod
    def sensor_to_device_id(sensorname):
        """Convert sensor name to Google device ID."""
        return f"aqi-sensor-{sensorname}"

    @staticmethod
    def device_id_to_sensor(device_id):
        """Convert Google device ID to sensor name, or None if invalid."""
        prefix = "aqi-sensor-"
        if device_id.startswith(prefix):
            return device_id[len(prefix):]
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

        # Define units for each Google sensor type
        GOOGLE_UNITS = {
            'AirQuality': 'AQI',
            'PM1': 'MICROGRAMS_PER_CUBIC_METER',
            'PM2.5': 'MICROGRAMS_PER_CUBIC_METER',
            'PM10': 'MICROGRAMS_PER_CUBIC_METER',
            'AmbientTemperature': 'CELSIUS',
            'AmbientHumidity': 'PERCENT'
        }

        for friendly_name, sensor_name in self.room_mapping.items():
            device_id = self.sensor_to_device_id(sensor_name)

            # Get available data types for this sensor
            available_datatypes = self.pmsdb.get_datatypes_for_sensor(sensor_name)
            say(f"Available datatypes for {sensor_name}: {available_datatypes}")

            # Build list of supported sensor states
            sensor_states_supported = []
            for datatype_name in available_datatypes:
                if datatype_name in self.DATATYPE_TO_GOOGLE:
                    google_datatype = self.DATATYPE_TO_GOOGLE[datatype_name]
                    unit = GOOGLE_UNITS.get(google_datatype, 'UNKNOWN')

                    sensor_states_supported.append({
                        "name": google_datatype,
                        "numericCapabilities": {
                            "rawValueUnit": unit
                        }
                    })

            # Skip sensor if no supported data types
            if not sensor_states_supported:
                say(f"Skipping {sensor_name} - no supported data types")
                continue

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
                    "sensorStatesSupported": sensor_states_supported
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
            sensor_name = self.device_id_to_sensor(device_id)
            if not sensor_name:
                continue

            # Get all latest values for this sensor (single query)
            latest_values = self.pmsdb.get_latest_values_for_sensor(sensor_name)
            say(f"Latest values for {sensor_name}: {latest_values}")

            # Build sensor states for supported datatypes
            sensor_states = []
            for datatype_name, value in latest_values.items():
                # Check if we have a mapping for this datatype
                if datatype_name not in self.DATATYPE_TO_GOOGLE:
                    continue

                google_datatype = self.DATATYPE_TO_GOOGLE[datatype_name]

                # Round if it's an integer-like value
                if datatype_name in ['aqi2.5', 'pm1.0', 'pm2.5', 'pm10.0']:
                    value = round(value)

                sensor_states.append({
                    "name": google_datatype,
                    "rawValue": value
                })

            if not sensor_states:
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
                    "currentSensorStateData": sensor_states
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
