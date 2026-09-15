.PHONY: all validate replay diffs database report clean

all: report

validate:
	mkdir -p /app/output
	xxd -l 8 /app/journal.bin > /app/output/header_hex.txt
	xxd -l 6 -p /app/journal.bin | grep -q "505445444954"
	xxd -s 6 -l 1 -p /app/journal.bin | grep -q "01"
	touch /app/output/journal_valid.stamp

replay: validate
	python3 /app/replay.py replay

diffs: replay
	python3 /app/replay.py diffs

database: diffs
	python3 /app/replay.py database

report: database
	echo "=== Version Report ===" > /app/output/report.txt
	sqlite3 -header -column /app/output/versions.db "SELECT id, line_count, char_count FROM snapshots ORDER BY id;" >> /app/output/report.txt
	echo "" >> /app/output/report.txt
	echo "--- Diff Summary ---" >> /app/output/report.txt
	sqlite3 -header -column /app/output/versions.db "SELECT SUM(additions) as total_additions, SUM(deletions) as total_deletions FROM diffs;" >> /app/output/report.txt

clean:
	rm -rf /app/output
