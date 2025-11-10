#!/usr/bin/env python3

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

import argparse
import cherrypy
import json
import os
import sys
import yaml
import secrets
import hashlib
import hmac
import time
import html
import urllib.parse

# project libraries
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.mylogging import say
import server.pms5003db as pms5003db


class GoogleSmartHomeIntegration:
    """Smart Home integration for air quality sensors."""

    def __init__(self, config):
        self.config = config
        self.pmsdb = pms5003db.PMS5003Database()

        # OAuth configuration
        # Convert to string to ensure type consistency for comparisons
        self.client_id = str(config.get('oauth_client_id', 'aqi-sensors'))
        self.client_secret = config.get('oauth_client_secret')
        if not self.client_secret or not str(self.client_secret).strip():
            raise ValueError("oauth_client_secret is required in config file")
        self.client_secret = str(self.client_secret)

        # OAuth redirect URI - must match what's configured in Google Console
        # For security, we validate redirects against this
        self.redirect_uri = config.get('oauth_redirect_uri', 'https://oauth-redirect.googleusercontent.com/r/')

        # Map friendly names to sensor names - REQUIRED
        room_mapping = config.get('room_mapping')
        if not room_mapping:
            raise ValueError("room_mapping is required in config file")
        # Validate room_mapping is a dictionary
        if not isinstance(room_mapping, dict):
            raise ValueError("room_mapping in config must be a dictionary")
        if len(room_mapping) == 0:
            raise ValueError("room_mapping must contain at least one room")
        self.room_mapping = room_mapping

        # In-memory token storage (for single-user, personal use)
        # For production with multiple users, use a database
        self.auth_codes = {}  # code -> {'username': str, 'expires': time}
        self.tokens = {}  # access_token -> {'username': str, 'refresh_token': str, 'expires': time}
        self.refresh_tokens = {}  # refresh_token -> {'username': str, 'access_token': str}

        # Simple username/password (for personal use) - REQUIRED
        # In production, integrate with your actual user system
        self.username = config.get('username')
        if not self.username or not str(self.username).strip():
            raise ValueError("username is required in config file")
        password = config.get('password')
        if not password or not str(password).strip():
            raise ValueError("password is required in config file")
        self.password_hash = hashlib.sha256(
            str(password).encode()
        ).hexdigest()

        # Load HTML template for OAuth login page
        template_path = os.path.join(
            os.path.dirname(__file__),
            'google-home-smarthome-login.html'
        )
        try:
            with open(template_path, 'r') as f:
                self.login_html_template = f.read()
        except FileNotFoundError:
            raise ValueError(
                f"Login template not found: {template_path}"
            )

    def verify_password(self, username, password):
        """Verify username and password."""
        if username != self.username:
            return False
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        # Use constant-time comparison to prevent timing attacks
        return hmac.compare_digest(password_hash, self.password_hash)

    def verify_access_token(self, token):
        """Verify an access token. Returns username if valid, None otherwise."""
        token_data = self.tokens.get(token)
        if not token_data:
            return None

        # Check expiration
        if time.time() > token_data['expires']:
            # Token expired - use pop() to avoid KeyError if already deleted
            self.tokens.pop(token, None)
            return None

        return token_data['username']

    def get_trailing_average(self, sensorname, averaging_sec=60):
        """
        Get the trailing average AQI for a sensor over the last N seconds.
        Returns None if no data available or on error.
        """
        try:
            db = self.pmsdb.get_raw_db()
            cursor = db.cursor()

            sensorid = self.pmsdb.get_sensorid_by_name(sensorname)
            if not sensorid:
                say(f"Unknown sensor name: {sensorname}")
                return None

            datatype = self.pmsdb.get_datatype_by_name('aqi2.5')
            if not datatype:
                say("ERROR: 'aqi2.5' datatype not found in database")
                return None

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

            row = cursor.fetchone()
            db.commit()

            avg_value = row[0]

            if avg_value is None:
                return None

            return round(avg_value)
        except Exception as e:
            say(f"Database error getting AQI for {sensorname}: {e}")
            return None

    def _cleanup_expired_auth_codes(self):
        """Remove expired authorization codes."""
        now = time.time()
        expired = [code for code, data in self.auth_codes.items() if data['expires'] < now]
        for code in expired:
            del self.auth_codes[code]
        if expired:
            say(f"Cleaned up {len(expired)} expired auth codes")

    def _cleanup_expired_tokens(self):
        """Remove expired access tokens."""
        now = time.time()
        expired = [token for token, data in self.tokens.items() if data['expires'] < now]
        for token in expired:
            # Also remove the corresponding refresh token mapping
            refresh_token = self.tokens[token].get('refresh_token')
            if refresh_token and refresh_token in self.refresh_tokens:
                del self.refresh_tokens[refresh_token]
            del self.tokens[token]
        if expired:
            say(f"Cleaned up {len(expired)} expired access tokens")

    # ========================================================================
    # OAuth 2.0 Endpoints
    # ========================================================================

    def _extract_param(self, value):
        """Extract first value if parameter is a list (happens with duplicate params)."""
        return value[0] if isinstance(value, list) and value else value

    @cherrypy.expose
    def auth(self, client_id=None, redirect_uri=None, state=None,
             response_type=None, username=None, password=None):
        """
        OAuth authorization endpoint.

        GET: Show login form
        POST: Process login and redirect with auth code
        """
        # CherryPy may pass parameters as lists if they appear multiple times
        # (e.g., in both query string and POST body). Extract first value.
        client_id = self._extract_param(client_id)
        redirect_uri = self._extract_param(redirect_uri)
        state = self._extract_param(state)
        response_type = self._extract_param(response_type)
        username = self._extract_param(username)
        password = self._extract_param(password)

        # Debug logging
        say(f"auth() called: method={cherrypy.request.method}, client_id={client_id}, redirect_uri={redirect_uri}, state={state}, response_type={response_type}")

        # Verify required parameters
        if not client_id or not redirect_uri or not state or not response_type:
            raise cherrypy.HTTPError(400, "Missing required OAuth parameters")

        # Verify this is a valid request from Google
        if client_id != self.client_id:
            raise cherrypy.HTTPError(400, "Invalid client_id")

        if response_type != 'code':
            raise cherrypy.HTTPError(400, "Only 'code' response_type supported")

        # Verify redirect URI to prevent open redirect attacks
        if not redirect_uri.startswith(self.redirect_uri):
            say(f"Invalid redirect_uri: {redirect_uri}")
            raise cherrypy.HTTPError(400, "Invalid redirect_uri")

        if cherrypy.request.method == 'GET':
            # Show login form with proper HTML escaping
            substitutions = {
                '$CLIENT_ID': html.escape(client_id),
                '$REDIRECT_URI': html.escape(redirect_uri),
                '$STATE': html.escape(state),
                '$RESPONSE_TYPE': html.escape(response_type)
            }

            # Substitute values into template using simple string replacement
            html_output = self.login_html_template
            for var_name, value in substitutions.items():
                html_output = html_output.replace(var_name, value)
            return html_output
        else:
            # POST: Process login
            if not username or not password:
                raise cherrypy.HTTPError(400, "Username and password required")

            if not self.verify_password(username, password):
                raise cherrypy.HTTPError(403, "Invalid credentials")

            # Clean up expired auth codes before creating new one
            self._cleanup_expired_auth_codes()

            # Generate authorization code
            auth_code = secrets.token_urlsafe(32)
            self.auth_codes[auth_code] = {
                'username': username,
                'expires': time.time() + 600  # 10 minutes
            }

            # Redirect back to Google with auth code
            # Use proper URL encoding for parameters
            redirect_url = f"{redirect_uri}?code={urllib.parse.quote(auth_code)}&state={urllib.parse.quote(state)}"
            raise cherrypy.HTTPRedirect(redirect_url)

    @cherrypy.expose
    def token(self, **kwargs):
        """
        OAuth token exchange endpoint.

        Handles:
        - Authorization code exchange for access + refresh tokens
        - Refresh token exchange for new access token
        """
        say("token() ENTERED - top of function")

        # Set JSON response header
        cherrypy.response.headers['Content-Type'] = 'application/json'

        try:
            # Debug: log the incoming request
            content_type = cherrypy.request.headers.get('Content-Type', 'not set')
            say(f"token() called: Content-Type={content_type}")

            # Parse form data or JSON
            # Google typically sends form-encoded data, but we support both
            if content_type.startswith('application/json'):
                try:
                    data = cherrypy.request.json
                except (ValueError, AttributeError) as e:
                    say(f"Invalid JSON in token request: {e}")
                    cherrypy.response.status = 400
                    return json.dumps({"error": "invalid_request", "error_description": "Invalid JSON"})
            else:
                data = cherrypy.request.params

            say(f"token() data keys: {list(data.keys()) if hasattr(data, 'keys') else 'not a dict'}")

            client_id = self._extract_param(data.get('client_id'))
            client_secret = self._extract_param(data.get('client_secret'))
            grant_type = self._extract_param(data.get('grant_type'))

            # Debug logging
            say(f"token() parsed: grant_type={grant_type}, client_id={client_id}, client_secret={'***' if client_secret else None}")
        except Exception as e:
            say(f"EXCEPTION in token(): {e}")
            import traceback
            say(traceback.format_exc())
            cherrypy.response.status = 500
            return json.dumps({"error": "server_error", "error_description": str(e)})

        # Verify client credentials
        if client_id != self.client_id or client_secret != self.client_secret:
            say(f"Invalid client credentials: client_id match={client_id == self.client_id}, client_secret match={client_secret == self.client_secret}")
            cherrypy.response.status = 401
            return json.dumps({"error": "invalid_client"})

        if grant_type == 'authorization_code':
            # Exchange authorization code for tokens
            code = data.get('code')

            auth_data = self.auth_codes.get(code)
            if not auth_data:
                say(f"Invalid auth code: {code}")
                cherrypy.response.status = 400
                return json.dumps({"error": "invalid_grant"})

            # Check expiration
            if time.time() > auth_data['expires']:
                say("Auth code expired")
                del self.auth_codes[code]
                cherrypy.response.status = 400
                return json.dumps({"error": "invalid_grant"})

            # Generate tokens
            access_token = secrets.token_urlsafe(32)
            refresh_token = secrets.token_urlsafe(32)

            self.tokens[access_token] = {
                'username': auth_data['username'],
                'refresh_token': refresh_token,
                'expires': time.time() + 3600  # 1 hour
            }
            self.refresh_tokens[refresh_token] = {
                'username': auth_data['username'],
                'access_token': access_token
            }

            # Clean up auth code
            del self.auth_codes[code]

            say("token() returning successful auth_code exchange")
            return json.dumps({
                "token_type": "Bearer",
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": 3600
            })

        elif grant_type == 'refresh_token':
            # Exchange refresh token for new access token
            refresh_token = data.get('refresh_token')

            refresh_data = self.refresh_tokens.get(refresh_token)
            if not refresh_data:
                say(f"Invalid refresh token")
                cherrypy.response.status = 400
                return json.dumps({"error": "invalid_grant"})

            # Clean up expired tokens before creating new one
            self._cleanup_expired_tokens()

            # Invalidate old access token if it still exists
            old_access_token = refresh_data.get('access_token')
            if old_access_token and old_access_token in self.tokens:
                del self.tokens[old_access_token]

            # Generate new access token
            access_token = secrets.token_urlsafe(32)

            self.tokens[access_token] = {
                'username': refresh_data['username'],
                'refresh_token': refresh_token,
                'expires': time.time() + 3600  # 1 hour
            }

            # Update refresh token mapping to point to new access token
            self.refresh_tokens[refresh_token]['access_token'] = access_token

            say("token() returning successful refresh_token exchange")
            return json.dumps({
                "token_type": "Bearer",
                "access_token": access_token,
                "expires_in": 3600
            })

        else:
            say(f"Unsupported grant_type: {grant_type}")
            cherrypy.response.status = 400
            return json.dumps({"error": "unsupported_grant_type"})

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

        # Verify authorization
        auth_header = cherrypy.request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            cherrypy.response.status = 401
            return {"error": "Missing authorization"}

        access_token = auth_header[7:]  # Remove 'Bearer ' prefix
        username = self.verify_access_token(access_token)

        if not username:
            cherrypy.response.status = 401
            return {"error": "Invalid or expired token"}

        say(f"Smart Home request from {username}: {json.dumps(request_data, indent=2)}")

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
                    "defaultNames": [f"AQI Sensor"],
                    "name": f"{friendly_name.title()} Air Quality",
                    "nicknames": [friendly_name, f"{friendly_name} AQI", f"{friendly_name} air quality"]
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
                "agentUserId": self.username,
                "devices": devices
            }
        }

        say(f"SYNC response: {len(devices)} devices")
        return response

    def handle_query(self, request_id, input_data):
        """
        Handle QUERY intent - return current sensor states.
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
        """
        # In a production system, you'd revoke tokens for the specific user
        # For this simple implementation, we just return success
        say("DISCONNECT request received")

        return {
            "requestId": request_id,
            "payload": {}
        }


def main():
    parser = argparse.ArgumentParser(
        description="Google Smart Home integration for air quality sensors"
    )
    parser.add_argument(
        "-c", "--config",
        help="Path to config file (YAML format)",
        required=True
    )
    args = parser.parse_args()

    # Load config
    try:
        with open(args.config) as f:
            config = yaml.safe_load(f)

        # Validate config is a dictionary
        if not isinstance(config, dict):
            print(f"ERROR: Config file must contain a YAML dictionary, got {type(config).__name__}")
            sys.exit(1)

    except FileNotFoundError:
        print(f"ERROR: Config file not found: {args.config}")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"ERROR: Invalid YAML in config file: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to load config: {e}")
        sys.exit(1)

    # Configure CherryPy
    cherrypy.config.update({
        'server.socket_host': config.get('listen-host', '127.0.0.1'),
        'server.socket_port': config.get('listen-port', 15001),
        'server.socket_timeout': 30,
        'log.screen': True,
        'log.access_file': '',
        'log.error_file': '',
        'request.show_tracebacks': True,
        'request.show_mismatched_params': True,
    })

    say("Starting Google Smart Home integration service...")
    cherrypy.quickstart(GoogleSmartHomeIntegration(config), '/')


if __name__ == '__main__':
    main()
