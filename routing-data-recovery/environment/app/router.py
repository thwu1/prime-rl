#!/usr/bin/env python3
"""Router daemon - manages routing for a single network node.

Each router daemon:
- Fetches its routes from the control plane API
- Caches routes locally in JSON files
- Sends periodic heartbeats
- Handles graceful shutdown
"""

import json
import os
import sys
import time
import signal
import argparse
import logging

try:
    import requests
except ImportError:
    print("Error: 'requests' package required. Install with: pip3 install requests", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Network router daemon')
    parser.add_argument('node_name', help='Name of the node this router manages')
    parser.add_argument('--api-url', default='http://localhost:5000',
                        help='Control plane API URL (default: http://localhost:5000)')
    parser.add_argument('--cache-dir', default='/app/routers/cache',
                        help='Cache directory (default: /app/routers/cache)')
    parser.add_argument('--interval', type=int, default=30,
                        help='Update interval in seconds (default: 30)')
    args = parser.parse_args()

    # Setup logging
    os.makedirs('/app/logs', exist_ok=True)
    log_file = f'/app/logs/router_{args.node_name}.log'
    logging.basicConfig(
        filename=log_file, level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s'
    )

    # Write PID file
    pid_file = f'/var/run/router_{args.node_name}.pid'
    if os.path.exists(pid_file):
        try:
            with open(pid_file) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            logging.error(f"Router {args.node_name} already running (PID {old_pid})")
            print(f"Error: Router {args.node_name} already running (PID {old_pid})", file=sys.stderr)
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            os.remove(pid_file)

    os.makedirs(os.path.dirname(pid_file), exist_ok=True)
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

    logging.info(f"Router {args.node_name} starting (PID {os.getpid()})")

    def cleanup(signum, frame):
        logging.info(f"Router {args.node_name} shutting down (signal {signum})")
        if os.path.exists(pid_file):
            os.remove(pid_file)
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    # Main loop
    os.makedirs(args.cache_dir, exist_ok=True)
    cache_file = os.path.join(args.cache_dir, f'{args.node_name}.json')

    while True:
        try:
            resp = requests.get(
                f'{args.api_url}/routes/{args.node_name}', timeout=5
            )
            if resp.status_code == 200:
                routes = resp.json()
                with open(cache_file, 'w') as f:
                    json.dump(routes, f, indent=2)
                logging.info(f"Cache updated: {len(routes)} routes for {args.node_name}")
            else:
                logging.warning(f"API returned status {resp.status_code}")
        except requests.exceptions.ConnectionError:
            logging.warning("Cannot connect to control plane API")
        except Exception as e:
            logging.error(f"Unexpected error: {e}")

        time.sleep(args.interval)


if __name__ == '__main__':
    main()
