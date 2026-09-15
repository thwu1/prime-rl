#!/bin/bash
set -euo pipefail

GUL_CSV="$1"
DIRECT_DIR="$2"
RI_DIR="$3"
OUTPUT_DB="$4"

WORK=$(mktemp -d)
PIPE_GROSS="${WORK}/gross_pipe"
GROSS_CSV="${WORK}/gross.csv"
NET_CSV="${WORK}/net.csv"

cleanup() {
    rm -rf "$WORK"
}
trap cleanup EXIT

mkfifo "$PIPE_GROSS"

# Background: capture gross output from the named pipe
cat "$PIPE_GROSS" > "$GROSS_CSV" &
PID_CAPTURE=$!

# Main pipeline: GUL -> direct fmcalc -> tee(FIFO for gross) -> ri fmcalc -n -> net
python3 /app/fmcalc.py -p "$DIRECT_DIR" < "$GUL_CSV" \
    | tee "$PIPE_GROSS" \
    | python3 /app/fmcalc.py -p "$RI_DIR" -n > "$NET_CSV"

wait $PID_CAPTURE

# Import results into SQLite database
python3 -c "
import csv, sqlite3, sys

db_path = sys.argv[1]
gross_csv = sys.argv[2]
net_csv = sys.argv[3]

conn = sqlite3.connect(db_path)
conn.execute('CREATE TABLE gross_loss(event_id INTEGER, output_id INTEGER, sidx INTEGER, loss REAL)')
conn.execute('CREATE TABLE net_loss(event_id INTEGER, output_id INTEGER, sidx INTEGER, loss REAL)')
conn.execute('CREATE TABLE summary(event_id INTEGER, gross_total REAL, net_total REAL, ceded_total REAL)')

for table, path in [('gross_loss', gross_csv), ('net_loss', net_csv)]:
    with open(path) as f:
        for row in csv.DictReader(f):
            conn.execute(
                f'INSERT INTO {table} VALUES(?,?,?,?)',
                (int(row['event_id']), int(row['output_id']),
                 int(row['sidx']), float(row['loss']))
            )

conn.execute('''
    INSERT INTO summary (event_id, gross_total, net_total, ceded_total)
    SELECT g.event_id, g.gt, COALESCE(n.nt, 0), g.gt - COALESCE(n.nt, 0)
    FROM (SELECT event_id, SUM(loss) AS gt FROM gross_loss GROUP BY event_id) g
    LEFT JOIN (SELECT event_id, SUM(loss) AS nt FROM net_loss GROUP BY event_id) n
    ON g.event_id = n.event_id
''')
conn.commit()
conn.close()
" "$OUTPUT_DB" "$GROSS_CSV" "$NET_CSV"

exit 0
