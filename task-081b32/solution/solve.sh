#!/bin/bash

cat > /app/validate.sh << 'SCRIPT'
#!/bin/bash
cd /app
python3 /solution/analyzer.py
SCRIPT
chmod +x /app/validate.sh
bash /app/validate.sh
