#!/bin/bash
service postgresql start
sleep 2
exec tail -f /dev/null
