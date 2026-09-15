#!/bin/bash

cp /solution/sysy_compiler.py /app/sysy_compiler.py
chmod +x /app/sysy_compiler.py

# Create executable wrapper that invokes the Python compiler
printf '#!/bin/bash\nexec python3 -u /app/sysy_compiler.py "$@"\n' > /app/sysy_compiler
chmod +x /app/sysy_compiler
