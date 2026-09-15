#!/bin/bash
# Strategy C: Binary file and multiline support
rg -a -U 'code=(E\d{3})\s+msg="([^"]*)"' /app/logs/ --no-filename -o -r '$1,$2'
