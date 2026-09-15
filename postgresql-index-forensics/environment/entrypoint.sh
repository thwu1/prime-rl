#!/bin/bash
PG_VER=$(ls /etc/postgresql/ | head -1)
pg_ctlcluster $PG_VER main start
exec tail -f /dev/null
