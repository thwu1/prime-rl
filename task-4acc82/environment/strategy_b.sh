#!/bin/bash
# Strategy B: Case-insensitive matching with hidden file support
rg -i --hidden 'code=([eE]\d{3}) msg="([^"]*)"' /app/logs/ --no-filename -o -r '$1,$2'
