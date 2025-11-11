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

        # Load user configuration
        self.users = config.get('users', {})
        if not self.users:
            raise ValueError("users configuration is required in config file")
        if not isinstance(self.users, dict):
            raise ValueError("users must be a dictionary")

        # Initialize OAuth handler with user authorization callback
        # Expose as nested object - CherryPy routes /auth/* to this object
        self.auth = OAuthHandler(config, self.is_user_authorized)

    def is_user_authorized(self, email):
        """
        Check if a user is authorized.

        Args:
            email: User email address

        Returns:
            True if user is authorized, False otherwise
        """
        return email in self.users

    # ========================================================================
    # Sensor Data Access
    # ========================================================================

    # Mapping from database datatype names to Google Home SensorState info
    # Note: Google only supports PM2.5 and PM10, not PM1
    # Temperature and humidity are handled separately (see handle_sync/handle_query)
    DATATYPE_TO_GOOGLE = {
        'aqi2.5': ('AirQuality', 'AQI'),
        'pm2.5': ('PM2.5', 'MICROGRAMS_PER_CUBIC_METER'),
        'pm10.0': ('PM10', 'MICROGRAMS_PER_CUBIC_METER'),
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
        email = self.auth.verify_access_token(access_token)

        if not email:
            cherrypy.response.status = 401
            return {"error": "Invalid or expired token"}

        say(f"Smart Home request from {email}: "
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
            return self.handle_sync(request_id, email)
        elif intent == 'action.devices.QUERY':
            return self.handle_query(request_id, inputs[0], email)
        elif intent == 'action.devices.EXECUTE':
            return self.handle_execute(request_id, inputs[0])
        elif intent == 'action.devices.DISCONNECT':
            return self.handle_disconnect(request_id)
        else:
            cherrypy.response.status = 400
            return {"error": f"Unknown intent: {intent}"}

    def handle_sync(self, request_id, email):
        """
        Handle SYNC intent - return list of available sensors.

        Args:
            request_id: Request ID from Google
            email: User email address

        Returns:
            SYNC response with device list
        """
        # Get user's room mapping
        user_config = self.users.get(email)
        if not user_config:
            say(f"No configuration found for user: {email}")
            return {
                "requestId": request_id,
                "payload": {
                    "agentUserId": email,
                    "devices": []
                }
            }

        room_mapping = user_config.get('room_mapping', {})
        if not room_mapping:
            say(f"No room_mapping for user: {email}")
            return {
                "requestId": request_id,
                "payload": {
                    "agentUserId": email,
                    "devices": []
                }
            }

        devices = []

        for friendly_name, sensor_name in room_mapping.items():
            device_id = self.sensor_to_device_id(sensor_name)

            # Get available data types for this sensor
            available_datatypes = self.pmsdb.get_datatypes_for_sensor(sensor_name)
            say(f"Available datatypes for {sensor_name}: {available_datatypes}")

            # Build list of supported sensor states and check for special traits
            sensor_states_supported = []
            has_temperature = False
            has_humidity = False

            for datatype_name in available_datatypes:
                if datatype_name == 'temperature_C':
                    has_temperature = True
                elif datatype_name == 'humidity':
                    has_humidity = True
                elif datatype_name in self.DATATYPE_TO_GOOGLE:
                    # SensorState trait
                    google_sensor_name, unit = self.DATATYPE_TO_GOOGLE[datatype_name]
                    sensor_states_supported.append({
                        "name": google_sensor_name,
                        "numericCapabilities": {
                            "rawValueUnit": unit
                        }
                    })

            # Skip sensor if no supported data types
            if not sensor_states_supported and not has_temperature and not has_humidity:
                say(f"Skipping {sensor_name} - no supported data types")
                continue

            # Build traits list
            traits = []
            attributes = {}

            if sensor_states_supported:
                traits.append("action.devices.traits.SensorState")
                attributes["sensorStatesSupported"] = sensor_states_supported

            if has_temperature:
                traits.append("action.devices.traits.TemperatureControl")
                attributes["queryOnlyTemperatureControl"] = True
                attributes["temperatureRange"] = {
                    "minThresholdCelsius": -40,
                    "maxThresholdCelsius": 100
                }
                attributes["temperatureUnitForUX"] = "C"

            if has_humidity:
                traits.append("action.devices.traits.HumiditySetting")
                attributes["queryOnlyHumiditySetting"] = True

            devices.append({
                "id": device_id,
                "type": "action.devices.types.SENSOR",
                "traits": traits,
                "name": {
                    "defaultNames": ["AQI Sensor"],
                    "name": f"{friendly_name.title()} Air Quality",
                    "nicknames": [
                        f"{friendly_name.title()} Air Quality",
                        f"{friendly_name} air quality",
                        f"{friendly_name} AQI"
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
                "attributes": attributes
            })

        response = {
            "requestId": request_id,
            "payload": {
                "agentUserId": email,
                "devices": devices
            }
        }

        say(f"SYNC response ({len(devices)} devices):\n"
            f"{json.dumps(response, indent=2)}")
        return response

    def handle_query(self, request_id, input_data, email):
        """
        Handle QUERY intent - return current sensor states.

        Args:
            request_id: Request ID from Google
            input_data: Input data containing device list
            email: User email address

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

            # Build sensor states and check for special traits
            sensor_states = []
            temperature_celsius = None
            humidity_percent = None

            for datatype_name, value in latest_values.items():
                # Round if it's a numeric type
                if isinstance(value, (int, float)):
                    value = round(value)

                # Temperature and humidity use separate traits
                if datatype_name == 'temperature_C':
                    temperature_celsius = value
                elif datatype_name == 'humidity':
                    humidity_percent = value
                elif datatype_name in self.DATATYPE_TO_GOOGLE:
                    # SensorState trait
                    google_sensor_name, _ = self.DATATYPE_TO_GOOGLE[datatype_name]
                    sensor_states.append({
                        "name": google_sensor_name,
                        "rawValue": value
                    })

            if not sensor_states and temperature_celsius is None and humidity_percent is None:
                # Sensor offline or no recent data
                device_states[device_id] = {
                    "online": False,
                    "status": "OFFLINE"
                }
            else:
                # Build device state
                device_state = {
                    "online": True,
                    "status": "SUCCESS"
                }

                # Add SensorState data if present
                if sensor_states:
                    device_state["currentSensorStateData"] = sensor_states

                # Add TemperatureControl data if present
                if temperature_celsius is not None:
                    device_state["temperatureAmbientCelsius"] = temperature_celsius

                # Add HumiditySetting data if present
                if humidity_percent is not None:
                    device_state["humidityAmbientPercent"] = humidity_percent

                device_states[device_id] = device_state

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
