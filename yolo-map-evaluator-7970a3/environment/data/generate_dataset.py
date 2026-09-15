#!/usr/bin/env python3
"""
Deterministic synthetic dataset generator for COCO-style mAP evaluation testing.
Populates a SQLite database with YOLO-format annotations that mirror
the class distribution of the GRAZPEDWRI-DX pediatric wrist fracture dataset.

"""
import os
import random
import sqlite3


def generate_dataset(seed=42, n_images=80, output_dir="/app/data"):
    random.seed(seed)

    db_path = os.path.join(output_dir, "annotations.db")
    os.makedirs(output_dir, exist_ok=True)

    # Remove existing DB to ensure clean state
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE images (
        image_id INTEGER PRIMARY KEY,
        filename TEXT NOT NULL,
        width INTEGER NOT NULL,
        height INTEGER NOT NULL
    )""")

    c.execute("""CREATE TABLE classes (
        class_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE ground_truth (
        ann_id INTEGER PRIMARY KEY AUTOINCREMENT,
        image_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        cx REAL NOT NULL,
        cy REAL NOT NULL,
        w REAL NOT NULL,
        h REAL NOT NULL,
        flags TEXT DEFAULT NULL,
        FOREIGN KEY (image_id) REFERENCES images(image_id),
        FOREIGN KEY (class_id) REFERENCES classes(class_id)
    )""")

    c.execute("""CREATE TABLE predictions (
        det_id INTEGER PRIMARY KEY AUTOINCREMENT,
        image_id INTEGER NOT NULL,
        class_id INTEGER NOT NULL,
        cx REAL NOT NULL,
        cy REAL NOT NULL,
        w REAL NOT NULL,
        h REAL NOT NULL,
        confidence REAL NOT NULL,
        FOREIGN KEY (image_id) REFERENCES images(image_id),
        FOREIGN KEY (class_id) REFERENCES classes(class_id)
    )""")

    classes = [
        "boneanomaly", "bonelesion", "foreignbody", "fracture", "metal",
        "periostealreaction", "pronatorsign", "softtissue", "text"
    ]
    for i, name in enumerate(classes):
        c.execute("INSERT INTO classes VALUES (?, ?)", (i, name))

    # Weights mimic GRAZPEDWRI-DX class imbalance
    class_weights = [0.05, 0.02, 0.01, 0.40, 0.15, 0.08, 0.12, 0.10, 0.07]

    for img_idx in range(n_images):
        img_name = f"image_{img_idx:04d}.png"
        w = random.choice([512, 640, 768, 1024, 1280])
        h = random.choice([512, 640, 768, 1024, 1280])
        c.execute("INSERT INTO images VALUES (?, ?, ?, ?)",
                  (img_idx, img_name, w, h))

        # Ground truth annotations (0..8 per image)
        n_gt = random.randint(0, 8)
        gt_entries = []
        for _ in range(n_gt):
            cls_id = random.choices(range(9), weights=class_weights, k=1)[0]
            cx = random.uniform(0.1, 0.9)
            cy = random.uniform(0.1, 0.9)
            bw = random.uniform(0.02, 0.4)
            bh = random.uniform(0.02, 0.4)
            # Clip to valid bounds
            bw = min(bw, min(cx, 1 - cx) * 2)
            bh = min(bh, min(cy, 1 - cy) * 2)

            # Some annotation tools append an optional difficulty/occlusion flag
            flags = None
            if random.random() < 0.3:
                flags = str(random.choice([0, 1]))

            c.execute(
                "INSERT INTO ground_truth "
                "(image_id, class_id, cx, cy, w, h, flags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (img_idx, cls_id, cx, cy, bw, bh, flags))
            gt_entries.append((cls_id, cx, cy, bw, bh))

        # Predictions: some match GT, some are false positives, some GT missed
        for cls_id, cx, cy, bw, bh in gt_entries:
            if random.random() < 0.75:  # 75% detection rate
                noise_scale = random.uniform(0.01, 0.08)
                pred_cx = cx + random.gauss(0, noise_scale)
                pred_cy = cy + random.gauss(0, noise_scale)
                pred_bw = bw * random.uniform(0.8, 1.2)
                pred_bh = bh * random.uniform(0.8, 1.2)
                pred_bw = max(0.01, pred_bw)
                pred_bh = max(0.01, pred_bh)
                conf = random.uniform(0.3, 0.99)

                # 10% chance of wrong class
                pred_cls = cls_id
                if random.random() < 0.1:
                    pred_cls = random.randint(0, 8)

                c.execute(
                    "INSERT INTO predictions "
                    "(image_id, class_id, cx, cy, w, h, confidence) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (img_idx, pred_cls, pred_cx, pred_cy,
                     pred_bw, pred_bh, conf))

        # Add false positive detections
        n_fp = random.randint(0, 3)
        for _ in range(n_fp):
            cls_id = random.choices(range(9), weights=class_weights, k=1)[0]
            cx = random.uniform(0.05, 0.95)
            cy = random.uniform(0.05, 0.95)
            bw = random.uniform(0.02, 0.3)
            bh = random.uniform(0.02, 0.3)
            conf = random.uniform(0.1, 0.7)
            c.execute(
                "INSERT INTO predictions "
                "(image_id, class_id, cx, cy, w, h, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (img_idx, cls_id, cx, cy, bw, bh, conf))

    conn.commit()

    total_gt = c.execute("SELECT COUNT(*) FROM ground_truth").fetchone()[0]
    total_pred = c.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    n_imgs = c.execute("SELECT COUNT(*) FROM images").fetchone()[0]

    conn.close()

    print(f"Generated {n_imgs} images in {db_path}")
    print(f"Total GT annotations: {total_gt}")
    print(f"Total predictions: {total_pred}")


if __name__ == "__main__":
    generate_dataset()
