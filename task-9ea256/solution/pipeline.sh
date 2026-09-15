#!/bin/bash
set -e

# ============================================================
# Phase 1: Convert HL7 v2 messages to FHIR R4 Transaction Bundles
# ============================================================
echo "Phase 1: HL7 v2 -> FHIR R4 conversion"
mkdir -p /app/output/bundles
python3 /app/converter.py --batch /app/hl7_input /app/output/bundles \
    --stats /app/output/conversion_stats.json

# ============================================================
# Phase 2: Extract resources from bundles, consolidate with bulk export
# ============================================================
echo "Phase 2: Resource extraction and consolidation"
mkdir -p /app/staging

# Extract Condition resources from all generated bundles using jq.
# Assign 'id' from the Bundle entry's fullUrl (strip urn:uuid: prefix).
jq -c '.entry[] | select(.resource.resourceType == "Condition") | .resource + {id: (.fullUrl | ltrimstr("urn:uuid:"))}' \
    /app/output/bundles/*.json > /tmp/hl7_conditions.ndjson

# Consolidate: bulk export conditions + HL7-derived conditions
cat /app/bulk_export/Condition.ndjson /tmp/hl7_conditions.ndjson > /app/staging/Condition.ndjson
echo "  Staged $(wc -l < /app/staging/Condition.ndjson) Condition resources"

# Observations and AllergyIntolerances: bulk export only
cp /app/bulk_export/Observation.ndjson /app/staging/Observation.ndjson
cp /app/bulk_export/AllergyIntolerance.ndjson /app/staging/AllergyIntolerance.ndjson

# ============================================================
# Phase 3: Terminology migration
# ============================================================
echo "Phase 3: ConceptMap-based terminology migration"
python3 /app/migrate.py

# ============================================================
# Phase 4: Assemble pipeline report from conversion + migration stats
# ============================================================
echo "Phase 4: Assembling pipeline report"
jq -s '{
  conversion: .[0],
  migration: {
    resources_processed: .[1].summary.resources_processed,
    translations: .[1].translations,
    unmapped_codes: .[1].unmapped_codes
  },
  summary: {
    hl7_messages_converted: .[0].messages_processed,
    total_resources_migrated: .[1].summary.resources_processed,
    codes_translated: .[1].summary.codes_translated,
    codes_unmapped: .[1].summary.codes_unmapped
  }
}' /app/output/conversion_stats.json /app/output/migration_stats.json \
   > /app/output/pipeline_report.json

echo "Pipeline complete. Report at /app/output/pipeline_report.json"
