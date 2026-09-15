#!/bin/bash
DB="/app/data/packages.db"
JSONL="/app/data/packages.jsonl"
rm -f "$DB"

# Import raw JSONL data
sqlite-utils insert "$DB" packages "$JSONL" --nl

# Parse author "Name <email>" into separate columns
sqlite-utils convert "$DB" packages author '
import re
match = re.match(r"^(.*?)\s*<(.+?)>$", value)
if match:
    return {"author_name": match.group(1).strip(), "author_email": match.group(2).strip()}
return {"author_name": value, "author_email": None}
' --multi

# Normalize date formats
sqlite-utils convert "$DB" packages first_release 'r.parsedate(value)'
sqlite-utils convert "$DB" packages last_update 'r.parsedatetime(value)'

# Convert tags from comma-separated to JSON arrays
sqlite-utils convert "$DB" packages tags 'r.jsonsplit(value)'

# Add primary key and fix column types
sqlite-utils transform "$DB" packages --pk id --type downloads integer

# Extract normalized lookup tables
sqlite-utils extract "$DB" packages author_name author_email \
    --table authors --rename author_name name --rename author_email email

sqlite-utils extract "$DB" packages category --table categories

sqlite-utils extract "$DB" packages license --table licenses

# Enable full-text search
sqlite-utils enable-fts "$DB" packages name tags

# Create summary view
sqlite-utils create-view "$DB" package_overview "
SELECT
    p.id, p.name, p.version,
    a.name as author_name, a.email as author_email,
    c.category, l.license,
    p.downloads, p.first_release, p.last_update,
    p.description, p.tags, p.status, p.homepage
FROM packages p
LEFT JOIN authors a ON p.author_id = a.id
LEFT JOIN categories c ON p.category_id = c.id
LEFT JOIN licenses l ON p.license_id = l.id
"

# Index foreign keys and enable WAL
sqlite-utils index-foreign-keys "$DB"
sqlite-utils enable-wal "$DB"

echo "Pipeline complete"
