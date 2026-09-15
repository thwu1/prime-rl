#!/bin/bash

cp /solution/pest_server.py /app/pest_server.py

printf '#!/bin/bash\nexec python3 /app/pest_server.py\n' > /app/run.sh
chmod +x /app/run.sh
