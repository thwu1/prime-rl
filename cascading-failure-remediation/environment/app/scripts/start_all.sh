#!/bin/bash
# Start all service-control instances and the gateway via supervisord.
exec supervisord -c /app/supervisord.conf
