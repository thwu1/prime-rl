#!/usr/bin/env python3
"""Generate synthetic multi-format CV datasets for the harmonization audit task."""

import json
import os
import struct
import zlib
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent


def make_png(path, width=640, height=480):
    """Create a minimal valid PNG with given dimensions."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    def chunk(ctype, data):
        c = ctype + data
        return (struct.pack('>I', len(data)) + c +
                struct.pack('>I', zlib.crc32(c) & 0xffffffff))

    scanline = b'\x00' + b'\x80\x80\x80' * width
    raw = scanline * height

    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(chunk(b'IHDR',
                      struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)))
        f.write(chunk(b'IDAT', zlib.compress(raw, 9)))
        f.write(chunk(b'IEND', b''))


# ---------------------------------------------------------------------------
# Team Alpha: COCO instances format
# Categories: car(1), truck(2), bus(3), person(4), cyclist(5),
#             traffic_light(6), stop_sign(7)
# Contains both bbox and polygon segmentation annotations.
# Polygon annotations have bbox=[0,0,0,0] and area=0 (not precomputed).
# ---------------------------------------------------------------------------
def create_coco_dataset(base_path):
    img_dir = os.path.join(base_path, 'images', 'train')
    ann_dir = os.path.join(base_path, 'annotations')
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(ann_dir, exist_ok=True)

    categories = [
        {"id": 1, "name": "car", "supercategory": "vehicle"},
        {"id": 2, "name": "truck", "supercategory": "vehicle"},
        {"id": 3, "name": "bus", "supercategory": "vehicle"},
        {"id": 4, "name": "person", "supercategory": "person"},
        {"id": 5, "name": "cyclist", "supercategory": "person"},
        {"id": 6, "name": "traffic_light", "supercategory": "infrastructure"},
        {"id": 7, "name": "stop_sign", "supercategory": "infrastructure"},
    ]

    # Each entry: (image_name, [(cat_name, ann_type, ann_data), ...])
    # ann_type "bbox": ann_data = (x, y, w, h)
    # ann_type "poly": ann_data = [x1, y1, x2, y2, ..., xn, yn]
    data = [
        ("img_a001", [("car", "bbox", (50, 100, 200, 150)),
                      ("person", "bbox", (400, 200, 60, 120))]),
        ("img_a002", [("truck", "bbox", (100, 50, 300, 200)),
                      ("bus", "bbox", (420, 100, 180, 220)),
                      ("traffic_light", "bbox", (550, 50, 20, 50))]),
        ("img_a003", [("car", "bbox", (50, 50, 150, 100)),
                      ("person", "poly",
                       [200, 100, 205, 100, 205, 180, 200, 180])]),
        ("img_a004", [("person", "bbox", (100, 100, 80, 180)),
                      ("cyclist", "poly",
                       [300, 200, 380, 200, 380, 300, 300, 300])]),
        ("img_a005", [("car", "bbox", (200, 200, 3, 180)),
                      ("truck", "bbox", (400, 100, 120, 80)),
                      ("stop_sign", "bbox", (580, 30, 25, 25))]),
        ("img_a006", [("car", "bbox", (50, 50, 100, 80)),
                      ("person", "bbox", (400, 300, 50, 100)),
                      ("car", "bbox", (250, 150, 120, 90))]),
        ("img_a007", [("traffic_light", "bbox", (500, 20, 18, 45)),
                      ("person", "bbox", (100, 200, 40, 60))]),
        ("img_a008", [("stop_sign", "poly",
                       [580, 30, 595, 30, 595, 42, 580, 42]),
                      ("car", "bbox", (300, 100, 180, 120))]),
    ]

    cat_name_to_id = {c["name"]: c["id"] for c in categories}
    images = []
    annotations = []
    ann_id = 1

    for img_idx, (img_name, anns) in enumerate(data, 1):
        make_png(os.path.join(img_dir, f"{img_name}.png"))
        images.append({
            "id": img_idx,
            "file_name": f"{img_name}.png",
            "height": 480,
            "width": 640,
        })
        for cat_name, ann_type, ann_data in anns:
            ann = {
                "id": ann_id,
                "image_id": img_idx,
                "category_id": cat_name_to_id[cat_name],
                "iscrowd": 0,
            }
            if ann_type == "bbox":
                x, y, w, h = ann_data
                ann["bbox"] = [x, y, w, h]
                ann["area"] = w * h
                ann["segmentation"] = []
            else:  # polygon — bbox and area intentionally not precomputed
                ann["bbox"] = [0, 0, 0, 0]
                ann["area"] = 0
                ann["segmentation"] = [ann_data]
            annotations.append(ann)
            ann_id += 1

    with open(os.path.join(ann_dir, 'instances_train.json'), 'w') as f:
        json.dump({"images": images, "annotations": annotations,
                   "categories": categories}, f, indent=2)


# ---------------------------------------------------------------------------
# Team Beta: Pascal VOC format
# Categories: vehicle, large_vehicle, walker, rider
# ---------------------------------------------------------------------------
def create_voc_dataset(base_path):
    img_dir = os.path.join(base_path, 'JPEGImages')
    ann_dir = os.path.join(base_path, 'Annotations')
    sets_dir = os.path.join(base_path, 'ImageSets', 'Main')
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(ann_dir, exist_ok=True)
    os.makedirs(sets_dir, exist_ok=True)

    # (image_name, [(label, xmin, ymin, xmax, ymax), ...])
    data = [
        ("img_b001", [("vehicle", 100, 50, 350, 250),
                      ("walker", 400, 100, 450, 300)]),
        ("img_b002", [("rider", 50, 200, 200, 350),
                      ("vehicle", 300, 100, 310, 110)]),
        ("img_b003", [("walker", 200, 100, 280, 300),
                      ("large_vehicle", 400, 200, 600, 350)]),
        ("img_b004", [("walker", 100, 50, 108, 450)]),
        ("img_b005", [("vehicle", 50, 50, 250, 200),
                      ("rider", 350, 150, 450, 280)]),
        ("img_b006", [("large_vehicle", 100, 100, 300, 250),
                      ("vehicle", 400, 50, 550, 200)]),
        ("img_b007", [("vehicle", 50, 200, 500, 210),
                      ("walker", 550, 100, 600, 280)]),
    ]

    img_names = []
    for img_name, anns in data:
        img_names.append(img_name)
        make_png(os.path.join(img_dir, f"{img_name}.png"))

        root = Element('annotation')
        SubElement(root, 'folder').text = 'JPEGImages'
        SubElement(root, 'filename').text = f'{img_name}.png'
        size_el = SubElement(root, 'size')
        SubElement(size_el, 'width').text = '640'
        SubElement(size_el, 'height').text = '480'
        SubElement(size_el, 'depth').text = '3'
        SubElement(root, 'segmented').text = '0'

        for label, xmin, ymin, xmax, ymax in anns:
            obj = SubElement(root, 'object')
            SubElement(obj, 'name').text = label
            SubElement(obj, 'pose').text = 'Unspecified'
            SubElement(obj, 'truncated').text = '0'
            SubElement(obj, 'difficult').text = '0'
            bndbox = SubElement(obj, 'bndbox')
            SubElement(bndbox, 'xmin').text = str(xmin)
            SubElement(bndbox, 'ymin').text = str(ymin)
            SubElement(bndbox, 'xmax').text = str(xmax)
            SubElement(bndbox, 'ymax').text = str(ymax)

        tree = ElementTree(root)
        indent(tree, space='  ')
        tree.write(os.path.join(ann_dir, f'{img_name}.xml'),
                   encoding='unicode', xml_declaration=True)

    with open(os.path.join(sets_dir, 'train.txt'), 'w') as f:
        for name in img_names:
            f.write(f'{name}\n')


# ---------------------------------------------------------------------------
# Team Gamma: YOLO format
# Categories: auto(0), truck(1), person(2), bike_rider(3), signal(4)
# All coordinates normalized to 800x600 images
# ---------------------------------------------------------------------------
def create_yolo_dataset(base_path):
    data_dir = os.path.join(base_path, 'obj_train_data')
    os.makedirs(data_dir, exist_ok=True)

    class_names = ['auto', 'truck', 'person', 'bike_rider', 'signal']

    # (image_name, [(class_idx, cx, cy, w, h), ...])
    data = [
        ("img_c001", [(0, 0.3, 0.4, 0.25, 0.3),
                      (2, 0.7, 0.5, 0.1, 0.15)]),
        ("img_c002", [(1, 0.5, 0.5, 0.35, 0.25),
                      (3, 0.2, 0.3, 0.1, 0.2)]),
        ("img_c003", [(0, 0.5, 0.5, 0.4, 0.35),
                      (2, 0.8, 0.7, 0.02, 0.02)]),
        ("img_c004", [(1, 0.3, 0.3, 0.3, 0.2),
                      (4, 0.8, 0.1, 0.05, 0.08)]),
        ("img_c005", [(3, 0.6, 0.5, 0.125, 0.2),
                      (0, 0.4, 0.4, 0.5, 0.02)]),
        ("img_c006", [(2, 0.5, 0.5, 0.15, 0.25),
                      (1, 0.3, 0.3, 0.2, 0.15)]),
        ("img_c007", [(0, 0.6, 0.6, 0.2, 0.15),
                      (4, 0.15, 0.1, 0.06, 0.1)]),
        ("img_c008", [(4, 0.9, 0.05, 0.01, 0.08)]),
    ]

    image_paths = []
    for img_name, anns in data:
        make_png(os.path.join(data_dir, f"{img_name}.png"), width=800,
                 height=600)
        image_paths.append(f"obj_train_data/{img_name}.png")

        with open(os.path.join(data_dir, f"{img_name}.txt"), 'w') as f:
            for class_idx, cx, cy, w, h in anns:
                f.write(f"{class_idx} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")

    with open(os.path.join(base_path, 'obj.names'), 'w') as f:
        for name in class_names:
            f.write(f"{name}\n")

    with open(os.path.join(base_path, 'obj.data'), 'w') as f:
        f.write(f"classes = {len(class_names)}\n")
        f.write("names = obj.names\n")
        f.write("train = train.txt\n")

    with open(os.path.join(base_path, 'train.txt'), 'w') as f:
        for path in image_paths:
            f.write(f"{path}\n")


if __name__ == '__main__':
    create_coco_dataset('/app/datasets/team_alpha')
    create_voc_dataset('/app/datasets/team_beta')
    create_yolo_dataset('/app/datasets/team_gamma')
    print("All datasets created successfully.")
