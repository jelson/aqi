"""
OAuth 2.0 handler for Google Smart Home integration.

Implements a simple OAuth 2.0 Authorization Code flow with:
- Authorization endpoint (login form)
- Token endpoint (code exchange and refresh)
- Token verification and management
- Persistent token storage
"""

import cherrypy
import json
import os
import secrets
import hashlib
import hmac
import time
import html
import urllib.parse

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from common.mylogging import say


class OAuthHandler:
    """Handles OAuth 2.0 authentication for Google Smart Home integration."""

    def __init__(self, config):
        """
        Initialize OAuth handler.

        Args:
            config: Configuration dictionary with keys:
                - oauth_client_id: OAuth client ID
                - oauth_client_secret: OAuth client secret
                - oauth_redirect_uri: Redirect URI (optional)
                - token_storage_dir: Directory for token persistence (required)
                - username: Username for authentication
                - password: Password for authentication
        """
        # OAuth configuration
        self.client_id = str(config.get('oauth_client_id', 'aqi-sensors'))
        self.client_secret = config.get('oauth_client_secret')
        if not self.client_secret or not str(self.client_secret).strip():
            raise ValueError(
                "oauth_client_secret is required in config file"
            )
        self.client_secret = str(self.client_secret)

        # OAuth redirect URI - must match Google Console configuration
        self.redirect_uri = config.get(
            'oauth_redirect_uri',
            'https://oauth-redirect.googleusercontent.com/r/'
        )

        # Token storage directory - must exist
        token_storage_dir = config.get('token_storage_dir')
        if not token_storage_dir or not str(token_storage_dir).strip():
            raise ValueError("token_storage_dir is required in config file")
        token_storage_dir = str(token_storage_dir).strip()
        if not os.path.isdir(token_storage_dir):
            raise ValueError(
                f"token_storage_dir does not exist: {token_storage_dir}"
            )

        self.token_file = os.path.join(token_storage_dir, 'google-smarthome-tokens.json')
        self.auth_codes = {}  # code -> {'username': str, 'expires': time}
        self.tokens = {}  # access_token -> data
        self.refresh_tokens = {}  # refresh_token -> data

        # Load persisted tokens if available
        self._load_tokens()

        # Simple username/password (for personal use)
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
            '..',
            'assets',
            'login.html'
        )
        try:
            with open(template_path, 'r') as f:
                self.login_html_template = f.read()
        except FileNotFoundError:
            raise ValueError(
                f"Login template not found: {template_path}"
            )

    def _load_tokens(self):
        """Load tokens from persistent storage."""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r') as f:
                    data = json.load(f)
                    self.tokens = data.get('tokens', {})
                    self.refresh_tokens = data.get('refresh_tokens', {})
                    say(f"Loaded {len(self.tokens)} access tokens and "
                        f"{len(self.refresh_tokens)} refresh tokens from "
                        f"{self.token_file}")
        except Exception as e:
            say(f"Warning: Failed to load tokens from "
                f"{self.token_file}: {e}")

    def _save_tokens(self):
        """Save tokens to persistent storage."""
        try:
            data = {
                'tokens': self.tokens,
                'refresh_tokens': self.refresh_tokens
            }
            with open(self.token_file, 'w') as f:
                json.dump(data, f)
            say(f"Saved {len(self.tokens)} access tokens and "
                f"{len(self.refresh_tokens)} refresh tokens to "
                f"{self.token_file}")
        except Exception as e:
            say(f"Warning: Failed to save tokens to "
                f"{self.token_file}: {e}")

    def verify_password(self, username, password):
        """
        Verify username and password.

        Args:
            username: Username to verify
            password: Password to verify

        Returns:
            True if credentials are valid, False otherwise
        """
        if username != self.username:
            return False
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        # Use constant-time comparison to prevent timing attacks
        return hmac.compare_digest(password_hash, self.password_hash)

    def verify_access_token(self, token):
        """
        Verify an access token.

        Args:
            token: Access token to verify

        Returns:
            Username if valid, None otherwise
        """
        token_data = self.tokens.get(token)
        if not token_data:
            return None

        # Check expiration
        if time.time() > token_data['expires']:
            # Token expired - use pop() to avoid KeyError if deleted
            self.tokens.pop(token, None)
            return None

        return token_data['username']

    def _cleanup_expired_auth_codes(self):
        """Remove expired authorization codes."""
        now = time.time()
        expired = [
            code for code, data in self.auth_codes.items()
            if data['expires'] < now
        ]
        for code in expired:
            del self.auth_codes[code]
        if expired:
            say(f"Cleaned up {len(expired)} expired auth codes")

    def _cleanup_expired_tokens(self):
        """Remove expired access tokens."""
        now = time.time()
        expired = [
            token for token, data in self.tokens.items()
            if data['expires'] < now
        ]
        for token in expired:
            # Also remove the corresponding refresh token mapping
            refresh_token = self.tokens[token].get('refresh_token')
            if refresh_token and refresh_token in self.refresh_tokens:
                del self.refresh_tokens[refresh_token]
            del self.tokens[token]
        if expired:
            say(f"Cleaned up {len(expired)} expired access tokens")
            # Persist changes to disk
            self._save_tokens()

    def _extract_param(self, value):
        """
        Extract first value if parameter is a list.

        This happens when duplicate params appear in both query string
        and POST body.

        Args:
            value: Parameter value (may be list or scalar)

        Returns:
            First value if list, otherwise the value itself
        """
        return value[0] if isinstance(value, list) and value else value

    @cherrypy.expose
    def auth(self, client_id=None, redirect_uri=None, state=None,
             response_type=None, username=None, password=None):
        """
        OAuth authorization endpoint.

        GET: Show login form
        POST: Process login and redirect with auth code

        Args:
            client_id: OAuth client ID
            redirect_uri: Redirect URI
            state: State parameter for CSRF protection
            response_type: Response type (must be 'code')
            username: Username (POST only)
            password: Password (POST only)

        Returns:
            HTML login form (GET) or redirect (POST)
        """
        # CherryPy may pass parameters as lists if they appear multiple times
        client_id = self._extract_param(client_id)
        redirect_uri = self._extract_param(redirect_uri)
        state = self._extract_param(state)
        response_type = self._extract_param(response_type)
        username = self._extract_param(username)
        password = self._extract_param(password)

        # Debug logging
        say(f"auth() called: method={cherrypy.request.method}, "
            f"client_id={client_id}, redirect_uri={redirect_uri}, "
            f"state={state}, response_type={response_type}")

        # Verify required parameters
        if not client_id or not redirect_uri or not state or \
           not response_type:
            raise cherrypy.HTTPError(400, "Missing required OAuth params")

        # Verify this is a valid request from Google
        if client_id != self.client_id:
            raise cherrypy.HTTPError(400, "Invalid client_id")

        if response_type != 'code':
            raise cherrypy.HTTPError(
                400, "Only 'code' response_type supported"
            )

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

            # Substitute values into template
            html_output = self.login_html_template
            for var_name, value in substitutions.items():
                html_output = html_output.replace(var_name, value)
            return html_output
        else:
            # POST: Process login
            if not username or not password:
                raise cherrypy.HTTPError(
                    400, "Username and password required"
                )

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
            redirect_url = (
                f"{redirect_uri}?"
                f"code={urllib.parse.quote(auth_code)}&"
                f"state={urllib.parse.quote(state)}"
            )
            raise cherrypy.HTTPRedirect(redirect_url)

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def token(self, client_id=None, client_secret=None, grant_type=None,
              code=None, refresh_token=None, **kwargs):
        """
        OAuth token exchange endpoint.

        Per RFC 6749, accepts application/x-www-form-urlencoded requests only.

        Handles:
        - Authorization code exchange for access + refresh tokens
        - Refresh token exchange for new access token

        Args:
            client_id: OAuth client ID
            client_secret: OAuth client secret
            grant_type: 'authorization_code' or 'refresh_token'
            code: Authorization code (for grant_type=authorization_code)
            refresh_token: Refresh token (for grant_type=refresh_token)

        Returns:
            JSON response with tokens or error
        """
        # Extract parameters (may be lists from duplicate params)
        client_id = self._extract_param(client_id)
        client_secret = self._extract_param(client_secret)
        grant_type = self._extract_param(grant_type)
        code = self._extract_param(code)
        refresh_token = self._extract_param(refresh_token)

        say(f"token() called: grant_type={grant_type}, client_id={client_id}")

        # Verify client credentials
        if client_id != self.client_id or client_secret != self.client_secret:
            say("Invalid client credentials")
            cherrypy.response.status = 401
            return {"error": "invalid_client"}

        if grant_type == 'authorization_code':
            # Exchange authorization code for tokens

            auth_data = self.auth_codes.get(code)
            if not auth_data:
                say(f"Invalid auth code: {code}")
                cherrypy.response.status = 400
                return {"error": "invalid_grant"}

            # Check expiration
            if time.time() > auth_data['expires']:
                say("Auth code expired")
                del self.auth_codes[code]
                cherrypy.response.status = 400
                return {"error": "invalid_grant"}

            # Generate tokens
            access_token = secrets.token_urlsafe(32)
            new_refresh_token = secrets.token_urlsafe(32)

            self.tokens[access_token] = {
                'username': auth_data['username'],
                'refresh_token': new_refresh_token,
                'expires': time.time() + 3600  # 1 hour
            }
            self.refresh_tokens[new_refresh_token] = {
                'username': auth_data['username'],
                'access_token': access_token
            }

            # Clean up auth code
            del self.auth_codes[code]

            # Persist tokens to disk
            self._save_tokens()

            say("token() returning successful auth_code exchange")
            return {
                "token_type": "Bearer",
                "access_token": access_token,
                "refresh_token": new_refresh_token,
                "expires_in": 3600
            }

        elif grant_type == 'refresh_token':
            # Exchange refresh token for new access token
            refresh_data = self.refresh_tokens.get(refresh_token)
            if not refresh_data:
                say("Invalid refresh token")
                cherrypy.response.status = 400
                return {"error": "invalid_grant"}

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
            self.refresh_tokens[refresh_token]['access_token'] = \
                access_token

            # Persist tokens to disk
            self._save_tokens()

            say("token() returning successful refresh_token exchange")
            return {
                "token_type": "Bearer",
                "access_token": access_token,
                "expires_in": 3600
            }

        else:
            say(f"Unsupported grant_type: {grant_type}")
            cherrypy.response.status = 400
            return {"error": "unsupported_grant_type"}
