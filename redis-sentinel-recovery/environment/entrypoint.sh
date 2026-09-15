#!/bin/bash
mkdir -p /var/run /var/log/supervisor /var/log/redis
supervisord -c /etc/supervisor/supervisord.conf
exec tail -f /dev/null
