#!/bin/bash

pip3 install redis==5.0.0 -q

# Start Redis server
redis-server --daemonize yes --port 6379
sleep 1

# Install the reference messaging implementation
cp /solution/messaging_impl.py /app/hitchhiker/messaging.py
