#!/bin/bash

# Stage 1: Run main Python pipeline (format detection + data processing + audit report)
python3 /solution/pipeline.py

# Stage 2: jq analytics on the COCO output
COCO="/app/output/annotations/instances_train.json"
mkdir -p /app/output/pipeline

# Compute annotations-per-image histogram (keys are string counts)
HIST=$(jq '.annotations | group_by(.image_id) | [.[] | length | tostring] | group_by(.) | map({(.[0]): length}) | add' "$COCO")

# Count annotations with bbox area > 10000
LARGE=$(jq '[.annotations[] | select((.bbox[2] * .bbox[3]) > 10000)] | length' "$COCO")

# Count images with annotations spanning 2+ distinct categories
CROSS=$(jq '
  (.categories | map({(.id|tostring): .name}) | add) as $n |
  [.annotations | group_by(.image_id)[] |
   [.[] | $n[.category_id|tostring]] | unique | length |
   select(. >= 2)] | length
' "$COCO")

# Compute per-category area ranges (min/max)
RANGES=$(jq '
  (.categories | map({(.id|tostring): .name}) | add) as $n |
  [.annotations[] | {cat: $n[.category_id|tostring], area: (.bbox[2] * .bbox[3])}] |
  group_by(.cat) |
  map({(.[0].cat): {min: (map(.area) | min), max: (map(.area) | max)}}) |
  add
' "$COCO")

# Assemble coco_analytics.json
jq -n \
  --argjson hist "$HIST" \
  --argjson large "$LARGE" \
  --argjson cross "$CROSS" \
  --argjson ranges "$RANGES" \
  '{
    annotations_per_image_histogram: $hist,
    large_annotation_count: $large,
    cross_category_images: $cross,
    category_area_ranges: $ranges
  }' > /app/output/pipeline/coco_analytics.json

# Stage 3: Merge analytics fields into the audit report
jq --argjson a "$(cat /app/output/pipeline/coco_analytics.json)" \
  '. + {
    large_annotation_count: $a.large_annotation_count,
    cross_category_images: $a.cross_category_images,
    annotations_per_image_histogram: $a.annotations_per_image_histogram
  }' /app/output/audit_report.json > /tmp/audit_merged.json
mv /tmp/audit_merged.json /app/output/audit_report.json
