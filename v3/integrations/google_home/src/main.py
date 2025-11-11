#!/usr/bin/env python3

"""
Entry point for Google Smart Home integration service.
"""

import argparse
import cherrypy
import os
import sys
import yaml

# Add project root to path before importing project modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from integrations.google_home.src.googlehome import GoogleSmartHomeIntegration
from common.mylogging import say


def main():
    parser = argparse.ArgumentParser(
        description="Google Smart Home integration for air quality sensors"
    )
    parser.add_argument(
        "-c", "--config",
        help="Path to config file (YAML format)",
        required=True
    )
    parser.add_argument(
        "--test-query",
        metavar="SENSOR_NAME",
        help="Test mode: query sensor and exit (e.g., 'jer-bedroom')"
    )
    args = parser.parse_args()

    # Load config
    try:
        with open(args.config) as f:
            config = yaml.safe_load(f)

        # Validate config is a dictionary
        if not isinstance(config, dict):
            print(f"ERROR: Config file must contain a YAML dictionary, "
                  f"got {type(config).__name__}")
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

    # Test mode: query a sensor and exit
    if args.test_query:
        say(f"TEST MODE: Querying sensor '{args.test_query}'")
        googlehome = GoogleSmartHomeIntegration(config)

        # Build a QUERY request for this sensor
        device_id = googlehome.sensor_to_device_id(args.test_query)
        query_input = {
            'payload': {
                'devices': [
                    {'id': device_id}
                ]
            }
        }

        # Call the real QUERY handler (use first user's email for testing)
        test_email = list(config.get('users', {}).keys())[0] if config.get('users') else 'test@example.com'
        response = googlehome.handle_query('test-request-id', query_input, test_email)

        # Display the result
        import json
        print(json.dumps(response, indent=2))

        # Check if sensor was found and online
        device_state = response.get('payload', {}).get('devices', {}).get(device_id, {})
        if device_state.get('online'):
            sys.exit(0)
        else:
            print(f"\nERROR: Sensor '{args.test_query}' is offline or unavailable")
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
