Three research teams independently annotated driving-scene images for object detection. Each used a different annotation format and label vocabulary:

- `/app/datasets/team_alpha/` — COCO instances, 7 source categories
- `/app/datasets/team_beta/` — Pascal VOC, 4 source categories
- `/app/datasets/team_gamma/` — YOLO, 5 source categories

The unified label schema is at `/app/unified_schema.json` and quality filtering rules at `/app/quality_rules.json`.

Produce a unified, quality-controlled object detection dataset exported as COCO instances to `/app/output/`. Every annotation in the final dataset must be a bounding box (`[x, y, width, height]` format). Apply quality filters: remove annotations where `width * height < min_area` or `max(width/height, height/width) > max_aspect_ratio`. Exclude images with zero remaining annotations after filtering.

## Required outputs

`/app/output/annotations/` — COCO instances annotation JSON.

`/app/output/pipeline/format_detection.json` — Programmatically auto-detected source dataset format per team (actual detection results, not hardcoded values):
```json
{"team_name": "detected_format_string", ...}
```

`/app/output/pipeline/coco_analytics.json` — Analytics derived from the final COCO annotation JSON:
```json
{
    "annotations_per_image_histogram": {"<annotation_count>": <num_images>, ...},
    "large_annotation_count": <int>,
    "cross_category_images": <int>,
    "category_area_ranges": {"<category_name>": {"min": <number>, "max": <number>}, ...}
}
```
Histogram keys are string representations of per-image annotation counts. Large annotations have bbox area (`width * height`) exceeding 10000. Cross-category images contain annotations spanning 2+ distinct categories. Category names must be resolved from COCO category IDs.

`/app/output/audit_report.json`:
```json
{
    "total_items": <int>,
    "total_annotations": <int>,
    "categories": ["<sorted unified category names>"],
    "category_counts": {"<category>": <int>},
    "items_removed_by_filtering": <int>,
    "annotations_removed_by_filtering": <int>,
    "source_contributions": {
        "team_alpha": {"items": <int>, "annotations": <int>},
        "team_beta": {"items": <int>, "annotations": <int>},
        "team_gamma": {"items": <int>, "annotations": <int>}
    },
    "polygon_annotations_converted": <int>,
    "detected_formats": {"<team>": "<format_string>"},
    "large_annotation_count": <int>,
    "cross_category_images": <int>,
    "annotations_per_image_histogram": {"<ann_count>": <num_images>}
}
```

All numeric values are integers. `categories` sorted alphabetically. Analytics fields must be consistent between `audit_report.json` and `coco_analytics.json`. Source contributions must sum to overall totals. Category counts must sum to `total_annotations`.

Pre-installed: `datumaro` (CLI: `datum`, Python: `import datumaro`), `jq`.