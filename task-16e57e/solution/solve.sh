#!/bin/bash

pip3 install numpy==2.1.3 -q

cd /app

# Step 1: Extract coefficient data from MATLAB .mat file using octave-cli
octave-cli --silent --eval "load('/app/extra_coefficients.mat'); csvwrite('/tmp/tuned_v2.csv', tuned_v2);"

# Step 2: Insert tuned_v2 coefficients into the SQLite database
sqlite3 /app/coefficients.db "INSERT INTO coefficient_sets VALUES (3, 'tuned_v2', 'Tuned v2 coefficients from .mat file');"

python3 -c "
import csv, sqlite3
conn = sqlite3.connect('/app/coefficients.db')
c = conn.cursor()
with open('/tmp/tuned_v2.csv') as f:
    for i, row in enumerate(csv.reader(f)):
        a, b, cc = float(row[0]), float(row[1]), float(row[2])
        c.execute('INSERT INTO coefficients VALUES (3, ?, ?, ?, ?)', (i, a, b, cc))
conn.commit()
conn.close()
"

# Step 3: Write the library implementation
python3 /solution/solve_impl.py

# Step 4: Generate CSV verification report using sqlite3 CLI
sqlite3 -header -csv /app/coefficients.db "SELECT cs.name, COUNT(co.iteration) as num_iterations, AVG(co.a) as mean_a, AVG(co.b) as mean_b, AVG(co.c) as mean_c FROM coefficient_sets cs JOIN coefficients co ON cs.id = co.set_id GROUP BY cs.name ORDER BY cs.name;" > /app/verification_report.csv
