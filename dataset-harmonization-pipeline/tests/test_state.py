#!/usr/bin/env python3
"""Tests for the multi-format dataset reconciliation pipeline."""

import json
import os
import glob
import pytest

# ── Expected values (deterministic from input datasets) ───────────────────

EXPECTED_CATEGORIES = sorted(
    ["vehicle_small", "vehicle_large", "pedestrian", "cyclist", "traffic_signal"]
)

# Alpha: 8 images kept, 16 annotations; Beta: 6 images, 10 anns; Gamma: 7 images, 12 anns
EXPECTED_TOTAL_ITEMS = 21
EXPECTED_TOTAL_ANNOTATIONS = 38
EXPECTED_ITEMS_REMOVED = 2    # Beta img_b004 + Gamma img_c008
EXPECTED_ANNOTATIONS_REMOVED = 9  # 47 total before - 38 after

EXPECTED_CATEGORY_COUNTS = {
    "vehicle_small": 11,
    "vehicle_large": 8,
    "pedestrian": 9,
    "cyclist": 5,
    "traffic_signal": 5,
}

EXPECTED_SOURCE_CONTRIBUTIONS = {
    "team_alpha": {"items": 8, "annotations": 16},
    "team_beta": {"items": 6, "annotations": 10},
    "team_gamma": {"items": 7, "annotations": 12},
}

EXPECTED_POLYGON_CONVERTED = 3

MIN_AREA = 500
MAX_ASPECT_RATIO = 6.0

# ── jq analytics expected values ────────────────────────────────────────

EXPECTED_HISTOGRAM = {"1": 6, "2": 13, "3": 2}
EXPECTED_LARGE_ANNOTATION_COUNT = 23
EXPECTED_CROSS_CATEGORY_IMAGES = 15
EXPECTED_AREA_RANGES = {
    "cyclist": {"min": 8000, "max": 22500},
    "pedestrian": {"min": 2400, "max": 18000},
    "traffic_signal": {"min": 625, "max": 2880},
    "vehicle_large": {"min": 9600, "max": 60000},
    "vehicle_small": {"min": 8000, "max": 67200},
}


def load_coco_annotations():
    """Load all COCO annotation files from the output directory."""
    output_dir = "/app/output"
    ann_dir = os.path.join(output_dir, "annotations")

    all_images = []
    all_annotations = []
    all_categories = []
    seen_cat_ids = set()

    json_files = []
    if os.path.isdir(ann_dir):
        json_files = glob.glob(os.path.join(ann_dir, "*.json"))
    if not json_files:
        json_files = glob.glob(os.path.join(output_dir, "*.json"))
        json_files = [f for f in json_files if "audit_report" not in f]

    assert len(json_files) > 0, (
        f"No COCO annotation JSON files found in {output_dir} or {ann_dir}"
    )

    for jf in json_files:
        with open(jf) as f:
            data = json.load(f)
        all_images.extend(data.get("images", []))
        all_annotations.extend(data.get("annotations", []))
        for c in data.get("categories", []):
            if c["id"] not in seen_cat_ids:
                all_categories.append(c)
                seen_cat_ids.add(c["id"])

    return all_images, all_annotations, all_categories


# ===== Output existence tests =====

class TestOutputExists:
    def test_output_directory_exists(self):
        assert os.path.isdir("/app/output"), "/app/output/ does not exist"

    def test_coco_annotations_exist(self):
        images, annotations, categories = load_coco_annotations()
        assert len(images) > 0, "No images found in COCO output"
        assert len(annotations) > 0, "No annotations found in COCO output"
        assert len(categories) > 0, "No categories found in COCO output"

    def test_audit_report_exists(self):
        assert os.path.isfile("/app/output/audit_report.json"), (
            "audit_report.json not found"
        )


# ===== Pipeline artifacts tests =====

class TestPipelineArtifacts:
    """Verify pipeline artifacts exist and are structurally valid."""

    def test_pipeline_directory_exists(self):
        assert os.path.isdir("/app/output/pipeline"), (
            "/app/output/pipeline/ directory does not exist"
        )

    def test_format_detection_exists(self):
        assert os.path.isfile("/app/output/pipeline/format_detection.json"), (
            "format_detection.json not found in pipeline artifacts"
        )

    def test_format_detection_valid_json(self):
        with open("/app/output/pipeline/format_detection.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "format_detection.json must be a JSON object"

    def test_coco_analytics_exists(self):
        assert os.path.isfile("/app/output/pipeline/coco_analytics.json"), (
            "coco_analytics.json not found in pipeline artifacts"
        )

    def test_coco_analytics_valid_json(self):
        with open("/app/output/pipeline/coco_analytics.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "coco_analytics.json must be a JSON object"

    def test_coco_analytics_has_required_keys(self):
        with open("/app/output/pipeline/coco_analytics.json") as f:
            data = json.load(f)
        required = {
            "annotations_per_image_histogram",
            "large_annotation_count",
            "cross_category_images",
            "category_area_ranges",
        }
        missing = required - set(data.keys())
        assert not missing, f"coco_analytics.json missing keys: {missing}"


# ===== Format detection tests =====

class TestFormatDetection:
    """Verify datumaro format auto-detection results."""

    @pytest.fixture(autouse=True)
    def load_formats(self):
        with open("/app/output/pipeline/format_detection.json") as f:
            self.formats = json.load(f)

    def test_all_teams_present(self):
        for team in ["team_alpha", "team_beta", "team_gamma"]:
            assert team in self.formats, f"Missing format detection for {team}"

    def test_alpha_detected_as_coco(self):
        fmt = self.formats["team_alpha"].lower()
        assert "coco" in fmt, (
            f"Team Alpha should be detected as COCO format, got: "
            f"'{self.formats['team_alpha']}'"
        )

    def test_beta_detected_as_voc(self):
        fmt = self.formats["team_beta"].lower()
        assert "voc" in fmt, (
            f"Team Beta should be detected as VOC format, got: "
            f"'{self.formats['team_beta']}'"
        )

    def test_gamma_detected_as_yolo(self):
        fmt = self.formats["team_gamma"].lower()
        assert "yolo" in fmt, (
            f"Team Gamma should be detected as YOLO format, got: "
            f"'{self.formats['team_gamma']}'"
        )

    def test_format_strings_not_unknown(self):
        for team, fmt in self.formats.items():
            assert fmt.lower() != "unknown", (
                f"Format for {team} is 'unknown' — datumaro detection failed"
            )


# ===== COCO analytics tests =====

class TestCOCOAnalytics:
    """Verify jq-derived COCO analytics values."""

    @pytest.fixture(autouse=True)
    def load_analytics(self):
        with open("/app/output/pipeline/coco_analytics.json") as f:
            self.analytics = json.load(f)

    def test_histogram_1_annotation(self):
        hist = self.analytics["annotations_per_image_histogram"]
        assert int(hist.get("1", 0)) == EXPECTED_HISTOGRAM["1"], (
            f"Expected {EXPECTED_HISTOGRAM['1']} images with 1 annotation, "
            f"got {hist.get('1', 0)}"
        )

    def test_histogram_2_annotations(self):
        hist = self.analytics["annotations_per_image_histogram"]
        assert int(hist.get("2", 0)) == EXPECTED_HISTOGRAM["2"], (
            f"Expected {EXPECTED_HISTOGRAM['2']} images with 2 annotations, "
            f"got {hist.get('2', 0)}"
        )

    def test_histogram_3_annotations(self):
        hist = self.analytics["annotations_per_image_histogram"]
        assert int(hist.get("3", 0)) == EXPECTED_HISTOGRAM["3"], (
            f"Expected {EXPECTED_HISTOGRAM['3']} images with 3 annotations, "
            f"got {hist.get('3', 0)}"
        )

    def test_histogram_total_equals_image_count(self):
        hist = self.analytics["annotations_per_image_histogram"]
        total = sum(int(v) for v in hist.values())
        assert total == EXPECTED_TOTAL_ITEMS, (
            f"Histogram values sum to {total}, expected {EXPECTED_TOTAL_ITEMS}"
        )

    def test_large_annotation_count(self):
        assert self.analytics["large_annotation_count"] == EXPECTED_LARGE_ANNOTATION_COUNT, (
            f"Expected {EXPECTED_LARGE_ANNOTATION_COUNT} large annotations, "
            f"got {self.analytics['large_annotation_count']}"
        )

    def test_cross_category_images(self):
        assert self.analytics["cross_category_images"] == EXPECTED_CROSS_CATEGORY_IMAGES, (
            f"Expected {EXPECTED_CROSS_CATEGORY_IMAGES} cross-category images, "
            f"got {self.analytics['cross_category_images']}"
        )

    def test_category_area_ranges_all_present(self):
        ranges = self.analytics["category_area_ranges"]
        for cat in EXPECTED_CATEGORIES:
            assert cat in ranges, f"Missing area range for category '{cat}'"

    def test_vehicle_small_area_range(self):
        r = self.analytics["category_area_ranges"]["vehicle_small"]
        assert abs(r["min"] - EXPECTED_AREA_RANGES["vehicle_small"]["min"]) < 1, (
            f"vehicle_small min area: expected {EXPECTED_AREA_RANGES['vehicle_small']['min']}, got {r['min']}"
        )
        assert abs(r["max"] - EXPECTED_AREA_RANGES["vehicle_small"]["max"]) < 1, (
            f"vehicle_small max area: expected {EXPECTED_AREA_RANGES['vehicle_small']['max']}, got {r['max']}"
        )

    def test_vehicle_large_area_range(self):
        r = self.analytics["category_area_ranges"]["vehicle_large"]
        assert abs(r["min"] - EXPECTED_AREA_RANGES["vehicle_large"]["min"]) < 1
        assert abs(r["max"] - EXPECTED_AREA_RANGES["vehicle_large"]["max"]) < 1

    def test_pedestrian_area_range(self):
        r = self.analytics["category_area_ranges"]["pedestrian"]
        assert abs(r["min"] - EXPECTED_AREA_RANGES["pedestrian"]["min"]) < 1
        assert abs(r["max"] - EXPECTED_AREA_RANGES["pedestrian"]["max"]) < 1

    def test_cyclist_area_range(self):
        r = self.analytics["category_area_ranges"]["cyclist"]
        assert abs(r["min"] - EXPECTED_AREA_RANGES["cyclist"]["min"]) < 1
        assert abs(r["max"] - EXPECTED_AREA_RANGES["cyclist"]["max"]) < 1

    def test_traffic_signal_area_range(self):
        r = self.analytics["category_area_ranges"]["traffic_signal"]
        assert abs(r["min"] - EXPECTED_AREA_RANGES["traffic_signal"]["min"]) < 1
        assert abs(r["max"] - EXPECTED_AREA_RANGES["traffic_signal"]["max"]) < 1


# ===== COCO structure tests =====

class TestCOCOStructure:
    def test_categories_match_unified_schema(self):
        _, _, categories = load_coco_annotations()
        cat_names = sorted([c["name"] for c in categories])
        assert cat_names == EXPECTED_CATEGORIES, (
            f"Got {cat_names}, expected {EXPECTED_CATEGORIES}"
        )

    def test_total_images(self):
        images, _, _ = load_coco_annotations()
        assert len(images) == EXPECTED_TOTAL_ITEMS, (
            f"Expected {EXPECTED_TOTAL_ITEMS} images, got {len(images)}"
        )

    def test_total_annotations(self):
        _, annotations, _ = load_coco_annotations()
        assert len(annotations) == EXPECTED_TOTAL_ANNOTATIONS, (
            f"Expected {EXPECTED_TOTAL_ANNOTATIONS} annotations, "
            f"got {len(annotations)}"
        )

    def test_all_annotations_have_valid_category(self):
        _, annotations, categories = load_coco_annotations()
        valid_ids = {c["id"] for c in categories}
        for ann in annotations:
            assert ann["category_id"] in valid_ids, (
                f"Annotation {ann['id']} has invalid category_id "
                f"{ann['category_id']}"
            )

    def test_all_images_have_annotations(self):
        images, annotations, _ = load_coco_annotations()
        ids_with_anns = {ann["image_id"] for ann in annotations}
        img_ids = {img["id"] for img in images}
        empty = img_ids - ids_with_anns
        assert len(empty) == 0, (
            f"{len(empty)} images without annotations: {empty}"
        )

    def test_no_duplicate_annotation_ids(self):
        _, annotations, _ = load_coco_annotations()
        ids = [a["id"] for a in annotations]
        assert len(ids) == len(set(ids)), "Duplicate annotation IDs found"

    def test_no_duplicate_image_ids(self):
        images, _, _ = load_coco_annotations()
        ids = [img["id"] for img in images]
        assert len(ids) == len(set(ids)), "Duplicate image IDs found"

    def test_annotations_have_required_fields(self):
        _, annotations, _ = load_coco_annotations()
        required = {"id", "image_id", "category_id", "bbox"}
        for ann in annotations:
            missing = required - set(ann.keys())
            assert not missing, (
                f"Annotation {ann.get('id', '?')} missing fields: {missing}"
            )

    def test_all_bboxes_have_four_elements(self):
        _, annotations, _ = load_coco_annotations()
        for ann in annotations:
            assert len(ann["bbox"]) == 4, (
                f"Annotation {ann['id']} bbox has {len(ann['bbox'])} "
                f"elements, expected 4"
            )

    def test_no_zero_size_bboxes(self):
        """Ensure no bbox has zero width or height (polygon conversion done)."""
        _, annotations, _ = load_coco_annotations()
        for ann in annotations:
            w, h = ann["bbox"][2], ann["bbox"][3]
            assert w > 0 and h > 0, (
                f"Annotation {ann['id']} has zero-size bbox: {ann['bbox']}"
            )


# ===== Quality filter tests =====

class TestQualityFilters:
    def test_no_small_annotations(self):
        _, annotations, _ = load_coco_annotations()
        for ann in annotations:
            bbox = ann["bbox"]
            area = bbox[2] * bbox[3]
            assert area >= MIN_AREA, (
                f"Annotation {ann['id']} has area {area:.1f} < {MIN_AREA}"
            )

    def test_no_bad_aspect_ratio(self):
        _, annotations, _ = load_coco_annotations()
        for ann in annotations:
            bbox = ann["bbox"]
            w, h = bbox[2], bbox[3]
            if w > 0 and h > 0:
                ar = max(w / h, h / w)
                assert ar <= MAX_ASPECT_RATIO + 0.1, (
                    f"Annotation {ann['id']} has AR {ar:.2f} > "
                    f"{MAX_ASPECT_RATIO}"
                )


# ===== Category distribution tests =====

class TestCategoryDistribution:
    def test_category_counts(self):
        _, annotations, categories = load_coco_annotations()
        id_to_name = {c["id"]: c["name"] for c in categories}

        counts = {}
        for ann in annotations:
            name = id_to_name[ann["category_id"]]
            counts[name] = counts.get(name, 0) + 1

        for cat_name, expected in EXPECTED_CATEGORY_COUNTS.items():
            actual = counts.get(cat_name, 0)
            assert actual == expected, (
                f"'{cat_name}': expected {expected}, got {actual}"
            )


# ===== Polygon conversion tests =====

class TestPolygonConversion:
    """Verify polygon annotations were correctly converted to bboxes."""

    def test_cyclist_from_polygon_present(self):
        """Alpha img_a004 has cyclist as polygon [300,200,...,300,300].
        Correct bbox: [300,200,80,100], area=8000. Must survive filtering."""
        _, annotations, categories = load_coco_annotations()
        id_to_name = {c["id"]: c["name"] for c in categories}
        found = any(
            id_to_name.get(a["category_id"]) == "cyclist"
            and abs(a["bbox"][2] - 80) < 3
            and abs(a["bbox"][3] - 100) < 3
            and abs(a["bbox"][0] - 300) < 3
            and abs(a["bbox"][1] - 200) < 3
            for a in annotations
        )
        assert found, (
            "Cyclist annotation from Alpha polygon conversion not found. "
            "Polygon segmentation must be converted to bbox."
        )

    def test_narrow_person_polygon_filtered(self):
        """Alpha img_a003 person polygon has bbox width=5, area=400<500.
        Must NOT appear in output."""
        _, annotations, categories = load_coco_annotations()
        id_to_name = {c["id"]: c["name"] for c in categories}
        narrow = [
            a for a in annotations
            if id_to_name.get(a["category_id"]) == "pedestrian"
            and abs(a["bbox"][2] - 5) < 2
        ]
        assert len(narrow) == 0, (
            "Narrow person polygon (w=5, area=400) should have been filtered"
        )


# ===== Data provenance tests =====

class TestDataProvenance:
    """Verify data from all three source teams is present."""

    def test_alpha_marker(self):
        """Team Alpha car bbox(50,100,200,150) -> vehicle_small."""
        _, annotations, categories = load_coco_annotations()
        id_to_name = {c["id"]: c["name"] for c in categories}
        found = any(
            id_to_name.get(a["category_id"]) == "vehicle_small"
            and abs(a["bbox"][2] - 200) < 3
            and abs(a["bbox"][3] - 150) < 3
            and abs(a["bbox"][0] - 50) < 3
            for a in annotations
        )
        assert found, "Marker annotation from Team Alpha not found"

    def test_beta_marker(self):
        """Team Beta vehicle (100,50)-(350,250) w=250 h=200 -> vehicle_small."""
        _, annotations, categories = load_coco_annotations()
        id_to_name = {c["id"]: c["name"] for c in categories}
        found = any(
            id_to_name.get(a["category_id"]) == "vehicle_small"
            and abs(a["bbox"][2] - 250) < 3
            and abs(a["bbox"][3] - 200) < 3
            for a in annotations
        )
        assert found, "Marker annotation from Team Beta not found"

    def test_gamma_marker(self):
        """Team Gamma truck (0.5,0.5,0.35,0.25) -> vehicle_large w=280 h=150."""
        _, annotations, categories = load_coco_annotations()
        id_to_name = {c["id"]: c["name"] for c in categories}
        found = any(
            id_to_name.get(a["category_id"]) == "vehicle_large"
            and abs(a["bbox"][2] - 280) < 5
            and abs(a["bbox"][3] - 150) < 5
            for a in annotations
        )
        assert found, "Marker annotation from Team Gamma not found"

    def test_bus_maps_to_vehicle_large(self):
        """Alpha bus(420,100,180,220) -> vehicle_large (many-to-one mapping)."""
        _, annotations, categories = load_coco_annotations()
        id_to_name = {c["id"]: c["name"] for c in categories}
        found = any(
            id_to_name.get(a["category_id"]) == "vehicle_large"
            and abs(a["bbox"][2] - 180) < 3
            and abs(a["bbox"][3] - 220) < 3
            for a in annotations
        )
        assert found, "Bus -> vehicle_large many-to-one mapping not found"

    def test_stop_sign_maps_to_traffic_signal(self):
        """Alpha stop_sign bbox(580,30,25,25) -> traffic_signal."""
        _, annotations, categories = load_coco_annotations()
        id_to_name = {c["id"]: c["name"] for c in categories}
        found = any(
            id_to_name.get(a["category_id"]) == "traffic_signal"
            and abs(a["bbox"][2] - 25) < 3
            and abs(a["bbox"][3] - 25) < 3
            for a in annotations
        )
        assert found, (
            "stop_sign -> traffic_signal many-to-one mapping not found"
        )

    def test_traffic_signal_combined_count(self):
        """traffic_signal comes from Alpha traffic_light + stop_sign + Gamma signal."""
        _, annotations, categories = load_coco_annotations()
        id_to_name = {c["id"]: c["name"] for c in categories}
        count = sum(
            1 for a in annotations
            if id_to_name.get(a["category_id"]) == "traffic_signal"
        )
        assert count == 5, (
            f"Expected 5 traffic_signal annotations "
            f"(3 Alpha + 2 Gamma), got {count}"
        )

    def test_cyclist_combined_count(self):
        """cyclist from Alpha(1 polygon) + Beta rider(2) + Gamma bike_rider(2)."""
        _, annotations, categories = load_coco_annotations()
        id_to_name = {c["id"]: c["name"] for c in categories}
        count = sum(
            1 for a in annotations
            if id_to_name.get(a["category_id"]) == "cyclist"
        )
        assert count == 5, (
            f"Expected 5 cyclist annotations "
            f"(1 Alpha polygon + 2 Beta + 2 Gamma), got {count}"
        )


# ===== Audit report tests =====

class TestAuditReport:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/output/audit_report.json") as f:
            self.report = json.load(f)

    def test_total_items(self):
        assert self.report["total_items"] == EXPECTED_TOTAL_ITEMS

    def test_total_annotations(self):
        assert self.report["total_annotations"] == EXPECTED_TOTAL_ANNOTATIONS

    def test_categories(self):
        assert sorted(self.report["categories"]) == EXPECTED_CATEGORIES

    def test_category_counts(self):
        for cat, expected in EXPECTED_CATEGORY_COUNTS.items():
            actual = self.report["category_counts"].get(cat, 0)
            assert actual == expected, (
                f"report category_counts['{cat}']: "
                f"expected {expected}, got {actual}"
            )

    def test_items_removed(self):
        assert self.report["items_removed_by_filtering"] == EXPECTED_ITEMS_REMOVED

    def test_annotations_removed(self):
        assert self.report["annotations_removed_by_filtering"] == EXPECTED_ANNOTATIONS_REMOVED

    def test_source_contributions(self):
        src = self.report["source_contributions"]
        for team, expected in EXPECTED_SOURCE_CONTRIBUTIONS.items():
            assert team in src, f"Missing source contribution for {team}"
            assert src[team]["items"] == expected["items"], (
                f"{team} items: expected {expected['items']}, "
                f"got {src[team]['items']}"
            )
            assert src[team]["annotations"] == expected["annotations"], (
                f"{team} annotations: expected {expected['annotations']}, "
                f"got {src[team]['annotations']}"
            )

    def test_polygon_annotations_converted(self):
        assert self.report["polygon_annotations_converted"] == EXPECTED_POLYGON_CONVERTED

    def test_detected_formats_present(self):
        assert "detected_formats" in self.report, (
            "audit report missing 'detected_formats' field"
        )
        for team in ["team_alpha", "team_beta", "team_gamma"]:
            assert team in self.report["detected_formats"], (
                f"detected_formats missing {team}"
            )

    def test_detected_formats_correct_families(self):
        fmts = self.report["detected_formats"]
        assert "coco" in fmts["team_alpha"].lower(), (
            f"Alpha format should contain 'coco', got '{fmts['team_alpha']}'"
        )
        assert "voc" in fmts["team_beta"].lower(), (
            f"Beta format should contain 'voc', got '{fmts['team_beta']}'"
        )
        assert "yolo" in fmts["team_gamma"].lower(), (
            f"Gamma format should contain 'yolo', got '{fmts['team_gamma']}'"
        )

    def test_large_annotation_count(self):
        assert self.report["large_annotation_count"] == EXPECTED_LARGE_ANNOTATION_COUNT

    def test_cross_category_images(self):
        assert self.report["cross_category_images"] == EXPECTED_CROSS_CATEGORY_IMAGES

    def test_annotations_per_image_histogram(self):
        hist = self.report["annotations_per_image_histogram"]
        for k, expected_val in EXPECTED_HISTOGRAM.items():
            actual = int(hist.get(k, hist.get(int(k), 0)))
            assert actual == expected_val, (
                f"histogram['{k}']: expected {expected_val}, got {actual}"
            )

    def test_analytics_consistent_with_artifact(self):
        """Audit report analytics must match coco_analytics.json."""
        with open("/app/output/pipeline/coco_analytics.json") as f:
            analytics = json.load(f)
        assert self.report["large_annotation_count"] == analytics["large_annotation_count"], (
            "large_annotation_count mismatch between audit report and coco_analytics.json"
        )
        assert self.report["cross_category_images"] == analytics["cross_category_images"], (
            "cross_category_images mismatch between audit report and coco_analytics.json"
        )


# ===== Consistency tests =====

class TestReportConsistency:
    """Verify audit_report.json is consistent with COCO output."""

    def test_report_matches_coco_item_count(self):
        images, _, _ = load_coco_annotations()
        with open("/app/output/audit_report.json") as f:
            report = json.load(f)
        assert report["total_items"] == len(images), (
            f"Report says {report['total_items']} items but COCO has "
            f"{len(images)} images"
        )

    def test_report_matches_coco_annotation_count(self):
        _, annotations, _ = load_coco_annotations()
        with open("/app/output/audit_report.json") as f:
            report = json.load(f)
        assert report["total_annotations"] == len(annotations), (
            f"Report says {report['total_annotations']} annotations but COCO "
            f"has {len(annotations)}"
        )

    def test_source_contribution_totals(self):
        """Sum of source contributions must equal overall totals."""
        with open("/app/output/audit_report.json") as f:
            report = json.load(f)
        src = report["source_contributions"]
        total_items = sum(s["items"] for s in src.values())
        total_anns = sum(s["annotations"] for s in src.values())
        assert total_items == report["total_items"], (
            f"Source items sum {total_items} != total_items "
            f"{report['total_items']}"
        )
        assert total_anns == report["total_annotations"], (
            f"Source annotations sum {total_anns} != total_annotations "
            f"{report['total_annotations']}"
        )

    def test_category_counts_sum(self):
        """Sum of category_counts must equal total_annotations."""
        with open("/app/output/audit_report.json") as f:
            report = json.load(f)
        total = sum(report["category_counts"].values())
        assert total == report["total_annotations"], (
            f"Category counts sum {total} != total_annotations "
            f"{report['total_annotations']}"
        )

    def test_histogram_sums_to_total_items(self):
        """Histogram values must sum to total_items."""
        with open("/app/output/audit_report.json") as f:
            report = json.load(f)
        hist = report["annotations_per_image_histogram"]
        total = sum(int(v) for v in hist.values())
        assert total == report["total_items"], (
            f"Histogram sum {total} != total_items {report['total_items']}"
        )
