#!/bin/bash
# Strategy A: Basic extraction with default ripgrep settings
rg 'code=(E\d{3}) msg="(.+)"' /app/logs/ --no-filename -o -r '$1,$2'
