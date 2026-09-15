#!/bin/bash

pip3 install pyyaml==6.0.2 -q

cp /solution/converter.py /app/converter.py
cp /solution/pipeline.py /app/pipeline.py

cat > /app/pipeline.sh << 'EOFSCRIPT'
#!/bin/bash
cd /app
python3 /app/pipeline.py
EOFSCRIPT
chmod +x /app/pipeline.sh

/app/pipeline.sh
