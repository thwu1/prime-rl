#!/bin/bash

pip3 install pyyaml==6.0.2 -q

cp /solution/pipeline.py /app/pipeline.py

# Write a working Makefile (tabs are critical for Make rules)
python3 -c "
with open('/app/Makefile', 'w') as f:
    f.write('.PHONY: all clean\n\n')
    f.write('all:\n')
    f.write('\tpython3 /app/pipeline.py\n\n')
    f.write('clean:\n')
    f.write('\trm -rf /app/results/*\n')
"

make -C /app all
