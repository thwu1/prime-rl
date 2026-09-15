#!/bin/bash

pip3 install requests==2.32.3 -q

cp /solution/binding_site_annotator.py /app/binding_site_annotator.py
chmod +x /app/binding_site_annotator.py
