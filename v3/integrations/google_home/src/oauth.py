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
import urllib.request

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from common.mylogging import say


class OAuthHandler:
    """Handles OAuth 2.0 authentication for Google Smart Home integration."""

    def __init__(self, config, is_user_authorized_callback):
        """
        Initialize OAuth handler.

        Args:
            config: Configuration dictionary with keys:
                - oauth_client_id: Smart Home OAuth client ID
                - oauth_client_secret: Smart Home OAuth client secret
                - oauth_redirect_uri: Smart Home OAuth redirect URI (optional)
                - token_storage_dir: Directory for token persistence (required)
                - google_oauth_client_id: Google Sign-In client ID
                - google_oauth_client_secret: Google Sign-In client secret
            is_user_authorized_callback: Function that takes email (str) and returns bool
        """
        # Smart Home OAuth configuration
        self.client_id = str(config.get('oauth_client_id', 'aqi-sensors'))
        self.client_secret = config.get('oauth_client_secret')
        if not self.client_secret or not str(self.client_secret).strip():
            raise ValueError(
                "oauth_client_secret is required in config file"
            )
        self.client_secret = str(self.client_secret)

        # Smart Home OAuth redirect URI
        self.redirect_uri = config.get(
            'oauth_redirect_uri',
            'https://oauth-redirect.googleusercontent.com/r/'
        )

        # Google Sign-In OAuth configuration
        self.google_client_id = config.get('google_oauth_client_id')
        if not self.google_client_id or not str(self.google_client_id).strip():
            raise ValueError(
                "google_oauth_client_id is required in config file"
            )
        self.google_client_id = str(self.google_client_id)

        self.google_client_secret = config.get('google_oauth_client_secret')
        if not self.google_client_secret or not str(self.google_client_secret).strip():
            raise ValueError(
                "google_oauth_client_secret is required in config file"
            )
        self.google_client_secret = str(self.google_client_secret)

        # User authorization callback
        self.is_user_authorized = is_user_authorized_callback

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
        self.auth_codes = {}  # code -> {'email': str, 'expires': time}
        self.tokens = {}  # access_token -> data
        self.refresh_tokens = {}  # refresh_token -> data
        self.google_auth_states = {}  # state -> Smart Home OAuth params

        # Load persisted tokens if available
        self._load_tokens()

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

    def verify_google_token(self, id_token):
        """
        Verify Google ID token and extract user email.

        Args:
            id_token: Google ID token from OAuth callback

        Returns:
            User email if valid and authorized, None otherwise
        """
        try:
            # Verify token with Google's token info endpoint
            url = f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            # Verify audience matches our client ID
            if data.get('aud') != self.google_client_id:
                say(f"Token audience mismatch: {data.get('aud')}")
                return None

            # Extract email
            email = data.get('email')
            if not email:
                say("No email in token")
                return None

            # Check if user is authorized (via callback)
            if not self.is_user_authorized(email):
                say(f"User not authorized: {email}")
                return None

            say(f"Verified Google token for: {email}")
            return email

        except Exception as e:
            say(f"Error verifying Google token: {e}")
            return None

    def verify_access_token(self, token):
        """
        Verify an access token.

        Args:
            token: Access token to verify

        Returns:
            User email if valid, None otherwise
        """
        token_data = self.tokens.get(token)
        if not token_data:
            return None

        # Check expiration
        if time.time() > token_data['expires']:
            # Token expired - use pop() to avoid KeyError if deleted
            self.tokens.pop(token, None)
            return None

        return token_data['email']

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
             response_type=None):
        """
        OAuth authorization endpoint - redirects to Google Sign-In.

        Args:
            client_id: OAuth client ID (Smart Home)
            redirect_uri: Redirect URI (Smart Home)
            state: State parameter for CSRF protection (Smart Home)
            response_type: Response type (must be 'code')

        Returns:
            Redirect to Google OAuth
        """
        # CherryPy may pass parameters as lists if they appear multiple times
        client_id = self._extract_param(client_id)
        redirect_uri = self._extract_param(redirect_uri)
        state = self._extract_param(state)
        response_type = self._extract_param(response_type)

        # Debug logging
        say(f"auth() called: client_id={client_id}, "
            f"redirect_uri={redirect_uri}, state={state}, "
            f"response_type={response_type}")

        # Verify required parameters
        if not client_id or not redirect_uri or not state or \
           not response_type:
            raise cherrypy.HTTPError(400, "Missing required OAuth params")

        # Verify this is a valid request from Google Smart Home
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

        # Generate state parameter for Google OAuth flow
        # This state will link the Google callback back to this Smart Home auth request
        google_state = secrets.token_urlsafe(32)
        self.google_auth_states[google_state] = {
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'state': state,
            'expires': time.time() + 600  # 10 minutes
        }

        # Build redirect URI from the request (preserves scheme and host from reverse proxy)
        # Use absolute=True and include the scheme to get full URL
        base_url = cherrypy.url('/auth/callback', base=cherrypy.request.base, relative=False)

        # Build Google OAuth authorization URL
        google_auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={urllib.parse.quote(self.google_client_id)}&"
            f"redirect_uri={urllib.parse.quote(base_url)}&"
            f"response_type=code&"
            f"scope={urllib.parse.quote('openid email')}&"
            f"state={urllib.parse.quote(google_state)}"
        )

        say(f"Redirecting to Google OAuth: {google_auth_url}")
        say(f"Redirect URI: {base_url}")
        raise cherrypy.HTTPRedirect(google_auth_url)

    @cherrypy.expose
    def callback(self, code=None, state=None, error=None):
        """
        Google OAuth callback endpoint.

        Args:
            code: Authorization code from Google
            state: State parameter linking back to Smart Home auth request
            error: Error from Google (if auth failed)

        Returns:
            Redirect back to Google Smart Home with auth code
        """
        say(f"callback() called: code={code[:20] if code else None}..., "
            f"state={state[:20] if state else None}..., error={error}")

        # Handle error from Google
        if error:
            say(f"Google OAuth error: {error}")
            raise cherrypy.HTTPError(403, f"Google authentication failed: {error}")

        # Verify required parameters
        if not code or not state:
            raise cherrypy.HTTPError(400, "Missing code or state")

        # Look up the Smart Home auth request
        auth_request = self.google_auth_states.get(state)
        if not auth_request:
            say(f"Unknown or expired state: {state}")
            raise cherrypy.HTTPError(400, "Invalid or expired state")

        # Clean up expired states
        now = time.time()
        self.google_auth_states = {
            s: data for s, data in self.google_auth_states.items()
            if data['expires'] > now
        }

        # Remove this state (one-time use)
        del self.google_auth_states[state]

        # Exchange authorization code for tokens from Google
        try:
            # Build redirect URI from the request (must match what was sent to Google)
            callback_url = cherrypy.url('/auth/callback', base=cherrypy.request.base, relative=False)

            token_url = "https://oauth2.googleapis.com/token"
            token_data = {
                'code': code,
                'client_id': self.google_client_id,
                'client_secret': self.google_client_secret,
                'redirect_uri': callback_url,
                'grant_type': 'authorization_code'
            }

            req = urllib.request.Request(
                token_url,
                data=urllib.parse.urlencode(token_data).encode(),
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            with urllib.request.urlopen(req) as response:
                tokens = json.loads(response.read().decode())

            id_token = tokens.get('id_token')
            if not id_token:
                say("No id_token in Google response")
                raise cherrypy.HTTPError(500, "Failed to get user identity from Google")

            # Verify the ID token and extract email
            email = self.verify_google_token(id_token)
            if not email:
                raise cherrypy.HTTPError(403, "User not authorized")

            say(f"Successfully authenticated user: {email}")

        except urllib.error.HTTPError as e:
            say(f"Google token exchange failed: {e}")
            raise cherrypy.HTTPError(500, "Failed to exchange code with Google")
        except Exception as e:
            say(f"Error in Google OAuth callback: {e}")
            raise cherrypy.HTTPError(500, f"Authentication error: {e}")

        # Clean up expired auth codes
        self._cleanup_expired_auth_codes()

        # Generate authorization code for Smart Home
        auth_code = secrets.token_urlsafe(32)
        self.auth_codes[auth_code] = {
            'email': email,
            'expires': time.time() + 600  # 10 minutes
        }

        # Redirect back to Google Smart Home with auth code
        redirect_url = (
            f"{auth_request['redirect_uri']}?"
            f"code={urllib.parse.quote(auth_code)}&"
            f"state={urllib.parse.quote(auth_request['state'])}"
        )
        say(f"Redirecting back to Google Smart Home: {redirect_url}")
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
                'email': auth_data['email'],
                'refresh_token': new_refresh_token,
                'expires': time.time() + 3600  # 1 hour
            }
            self.refresh_tokens[new_refresh_token] = {
                'email': auth_data['email'],
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
                'email': refresh_data['email'],
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
