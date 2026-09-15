#!/bin/bash
# Container entrypoint: set up topology and keep alive
/app/scripts/setup_topology.sh
exec tail -f /dev/null
