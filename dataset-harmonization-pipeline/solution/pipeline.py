#!/usr/bin/env python3
"""
Multi-format CV dataset reconciliation pipeline.

Stage 1: Uses datumaro Python API for format auto-detection.
Stage 2: Reads COCO (with polygon segmentations), VOC, and YOLO datasets,
applies polygon->bbox conversion, label remapping (many-to-one), and
quality filters, then exports a unified COCO instances dataset with
an audit report (without analytics fields — those are added by jq in solve.sh).
"""

import json
import os
import struct
import subprocess
from xml.etree import ElementTree


# ── helpers ──────────────────────────────────────────────────────────────────

def get_png_dimensions(path):
    """Read width and height from a PNG IHDR chunk."""
    with open(path, 'rb') as f:
        f.read(8)   # PNG signature
        f.read(4)   # chunk length
        f.read(4)   # 'IHDR'
        w = struct.unpack('>I', f.read(4))[0]
        h = struct.unpack('>I', f.read(4))[0]
    return w, h


def polygon_to_bbox(segmentation):
    """Compute [x, y, w, h] bounding box from COCO polygon coordinates.
    segmentation is a flat list [x1, y1, x2, y2, ..., xn, yn]."""
    xs = segmentation[0::2]
    ys = segmentation[1::2]
    x_min = min(xs)
    y_min = min(ys)
    x_max = max(xs)
    y_max = max(ys)
    return [x_min, y_min, x_max - x_min, y_max - y_min]


# ── Stage 1: Format detection using datumaro ────────────────────────────────

def detect_format_datumaro(path):
    """Detect dataset format using datumaro's Python API or CLI."""
    # Try datumaro Python API
    try:
        import datumaro as dm
        env = dm.Environment()
        if hasattr(env, 'detect_dataset'):
            result = env.detect_dataset(path)
            if isinstance(result, dict):
                return max(result, key=result.get)
            if isinstance(result, list) and result:
                entry = result[0]
                if isinstance(entry, (tuple, list)):
                    return str(entry[0])
                return str(entry)
            if isinstance(result, str):
                return result
    except Exception:
        pass

    # Fallback: try Dataset.detect
    try:
        import datumaro as dm
        if hasattr(dm.Dataset, 'detect'):
            result = dm.Dataset.detect(path)
            if isinstance(result, str):
                return result
            if isinstance(result, list) and result:
                entry = result[0]
                return str(entry[0]) if isinstance(entry, (tuple, list)) else str(entry)
    except Exception:
        pass

    # Fallback: try importing and reading format property
    try:
        import datumaro as dm
        ds = dm.Dataset.import_from(path)
        fmt = getattr(ds, 'format', None) or getattr(ds, 'data_format', None)
        if fmt:
            return str(fmt)
    except Exception:
        pass

    # Last resort: datum CLI
    try:
        for cmd in [['datum', 'detect-format', path],
                    ['datum', 'detect', path]]:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split('\n'):
                    line = line.strip()
                    if ':' in line:
                        return line.split(':')[-1].strip()
                    if line and not line.startswith('#') and not line.startswith('='):
                        return line
    except Exception:
        pass

    return 'unknown'


os.makedirs('/app/output/pipeline', exist_ok=True)

teams_paths = [
    ('team_alpha', '/app/datasets/team_alpha'),
    ('team_beta', '/app/datasets/team_beta'),
    ('team_gamma', '/app/datasets/team_gamma'),
]

detected_formats = {}
for team, path in teams_paths:
    detected_formats[team] = detect_format_datumaro(path)

with open('/app/output/pipeline/format_detection.json', 'w') as f:
    json.dump(detected_formats, f, indent=2)

print(f"Format detection: {detected_formats}")


# ── load configuration ──────────────────────────────────────────────────────

with open('/app/unified_schema.json') as f:
    schema = json.load(f)
with open('/app/quality_rules.json') as f:
    rules = json.load(f)

MIN_AREA = rules['min_area']
MAX_AR = rules['max_aspect_ratio']
UNIFIED_CATS = sorted(schema['unified_categories'])
cat_name_to_id = {name: idx + 1 for idx, name in enumerate(UNIFIED_CATS)}

# Accumulators
all_images = []
all_annotations = []
total_anns_before = 0
total_items_before = 0
items_removed = 0
polygon_converted = 0
source_stats = {}
img_id = 1
ann_id = 1


def passes_quality(w, h):
    """Return True if bbox passes area and aspect-ratio filters."""
    area = w * h
    if area < MIN_AREA:
        return False
    if w > 0 and h > 0:
        ar = max(w / h, h / w)
        if ar > MAX_AR:
            return False
    return True


# ── Team Alpha: COCO instances ──────────────────────────────────────────────

alpha_map = schema['source_mappings']['team_alpha']['label_map']
coco_path = '/app/datasets/team_alpha/annotations/instances_train.json'

with open(coco_path) as f:
    coco = json.load(f)

alpha_cat_id_to_name = {c['id']: c['name'] for c in coco['categories']}

# Group annotations by image_id
alpha_anns_by_img = {}
for a in coco['annotations']:
    alpha_anns_by_img.setdefault(a['image_id'], []).append(a)

alpha_items = 0
alpha_anns = 0

for img_info in coco['images']:
    total_items_before += 1
    src_anns = alpha_anns_by_img.get(img_info['id'], [])
    total_anns_before += len(src_anns)

    filtered = []
    for a in src_anns:
        src_label = alpha_cat_id_to_name.get(a['category_id'])
        if src_label not in alpha_map:
            continue
        unified = alpha_map[src_label]

        # Handle polygon segmentation annotations
        bbox = a['bbox']
        if (bbox == [0, 0, 0, 0] or a.get('area', 0) == 0) and a.get('segmentation'):
            seg = a['segmentation']
            if isinstance(seg, list) and len(seg) > 0 and isinstance(seg[0], list):
                bbox = polygon_to_bbox(seg[0])
                polygon_converted += 1
            elif isinstance(seg, list) and len(seg) > 0 and isinstance(seg[0], (int, float)):
                bbox = polygon_to_bbox(seg)
                polygon_converted += 1

        x, y, w, h = bbox
        if not passes_quality(w, h):
            continue

        filtered.append({
            'id': ann_id,
            'image_id': img_id,
            'category_id': cat_name_to_id[unified],
            'bbox': [x, y, w, h],
            'area': w * h,
            'iscrowd': 0,
            'segmentation': [],
        })
        ann_id += 1

    if filtered:
        all_images.append({
            'id': img_id,
            'file_name': img_info['file_name'],
            'height': img_info['height'],
            'width': img_info['width'],
        })
        all_annotations.extend(filtered)
        alpha_items += 1
        alpha_anns += len(filtered)
        img_id += 1
    else:
        items_removed += 1

source_stats['team_alpha'] = {'items': alpha_items, 'annotations': alpha_anns}


# ── Team Beta: Pascal VOC ──────────────────────────────────────────────────

beta_map = schema['source_mappings']['team_beta']['label_map']
voc_base = '/app/datasets/team_beta'
voc_ann_dir = os.path.join(voc_base, 'Annotations')
voc_sets = os.path.join(voc_base, 'ImageSets', 'Main', 'train.txt')

with open(voc_sets) as f:
    voc_items = [line.strip() for line in f if line.strip()]

beta_items = 0
beta_anns = 0

for item_name in voc_items:
    total_items_before += 1
    xml_path = os.path.join(voc_ann_dir, f'{item_name}.xml')
    tree = ElementTree.parse(xml_path)
    root = tree.getroot()

    size_el = root.find('size')
    img_w = int(size_el.find('width').text)
    img_h = int(size_el.find('height').text)

    src_anns = root.findall('object')
    total_anns_before += len(src_anns)

    filtered = []
    for obj in src_anns:
        src_label = obj.find('name').text
        if src_label not in beta_map:
            continue
        unified = beta_map[src_label]
        bb = obj.find('bndbox')
        xmin = float(bb.find('xmin').text)
        ymin = float(bb.find('ymin').text)
        xmax = float(bb.find('xmax').text)
        ymax = float(bb.find('ymax').text)
        w = xmax - xmin
        h = ymax - ymin
        if not passes_quality(w, h):
            continue
        filtered.append({
            'id': ann_id,
            'image_id': img_id,
            'category_id': cat_name_to_id[unified],
            'bbox': [xmin, ymin, w, h],
            'area': w * h,
            'iscrowd': 0,
            'segmentation': [],
        })
        ann_id += 1

    if filtered:
        all_images.append({
            'id': img_id,
            'file_name': f'{item_name}.png',
            'height': img_h,
            'width': img_w,
        })
        all_annotations.extend(filtered)
        beta_items += 1
        beta_anns += len(filtered)
        img_id += 1
    else:
        items_removed += 1

source_stats['team_beta'] = {'items': beta_items, 'annotations': beta_anns}


# ── Team Gamma: YOLO ────────────────────────────────────────────────────────

gamma_map = schema['source_mappings']['team_gamma']['label_map']
yolo_base = '/app/datasets/team_gamma'

with open(os.path.join(yolo_base, 'obj.names')) as f:
    yolo_classes = [line.strip() for line in f if line.strip()]

with open(os.path.join(yolo_base, 'train.txt')) as f:
    yolo_img_paths = [line.strip() for line in f if line.strip()]

gamma_items = 0
gamma_anns = 0

for rel_img_path in yolo_img_paths:
    total_items_before += 1
    abs_img_path = os.path.join(yolo_base, rel_img_path)
    img_w, img_h = get_png_dimensions(abs_img_path)

    base = os.path.splitext(abs_img_path)[0]
    txt_path = base + '.txt'

    src_ann_count = 0
    filtered = []
    if os.path.isfile(txt_path):
        with open(txt_path) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 5:
                    continue
                src_ann_count += 1
                cls_idx = int(parts[0])
                cx_n, cy_n, w_n, h_n = (float(parts[1]), float(parts[2]),
                                         float(parts[3]), float(parts[4]))
                # Convert normalized center coords to pixel (x, y, w, h)
                bw = w_n * img_w
                bh = h_n * img_h
                bx = cx_n * img_w - bw / 2.0
                by = cy_n * img_h - bh / 2.0

                src_label = yolo_classes[cls_idx]
                if src_label not in gamma_map:
                    continue
                unified = gamma_map[src_label]

                if not passes_quality(bw, bh):
                    continue
                filtered.append({
                    'id': ann_id,
                    'image_id': img_id,
                    'category_id': cat_name_to_id[unified],
                    'bbox': [round(bx, 2), round(by, 2),
                             round(bw, 2), round(bh, 2)],
                    'area': round(bw * bh, 2),
                    'iscrowd': 0,
                    'segmentation': [],
                })
                ann_id += 1

    total_anns_before += src_ann_count

    if filtered:
        fname = os.path.basename(rel_img_path)
        all_images.append({
            'id': img_id,
            'file_name': fname,
            'height': img_h,
            'width': img_w,
        })
        all_annotations.extend(filtered)
        gamma_items += 1
        gamma_anns += len(filtered)
        img_id += 1
    else:
        items_removed += 1

source_stats['team_gamma'] = {'items': gamma_items, 'annotations': gamma_anns}


# ── Write COCO output ───────────────────────────────────────────────────────

out_dir = '/app/output'
ann_dir = os.path.join(out_dir, 'annotations')
os.makedirs(ann_dir, exist_ok=True)

categories = [{'id': cat_name_to_id[n], 'name': n} for n in UNIFIED_CATS]

coco_output = {
    'images': all_images,
    'annotations': all_annotations,
    'categories': categories,
}

with open(os.path.join(ann_dir, 'instances_train.json'), 'w') as f:
    json.dump(coco_output, f, indent=2)


# ── Compute and write initial audit report ───────────────────────────────────
# Note: large_annotation_count, cross_category_images, and
# annotations_per_image_histogram are added by jq in solve.sh

cat_counts = {}
for a in all_annotations:
    name = next(c['name'] for c in categories if c['id'] == a['category_id'])
    cat_counts[name] = cat_counts.get(name, 0) + 1

report = {
    'total_items': len(all_images),
    'total_annotations': len(all_annotations),
    'categories': UNIFIED_CATS,
    'category_counts': cat_counts,
    'items_removed_by_filtering': items_removed,
    'annotations_removed_by_filtering': total_anns_before - len(all_annotations),
    'source_contributions': source_stats,
    'polygon_annotations_converted': polygon_converted,
    'detected_formats': detected_formats,
}

with open(os.path.join(out_dir, 'audit_report.json'), 'w') as f:
    json.dump(report, f, indent=2)

print(f"Pipeline complete: {report['total_items']} items, "
      f"{report['total_annotations']} annotations.")
print(f"Removed {report['annotations_removed_by_filtering']} annotations, "
      f"{report['items_removed_by_filtering']} empty items.")
print(f"Converted {report['polygon_annotations_converted']} polygon annotations.")
