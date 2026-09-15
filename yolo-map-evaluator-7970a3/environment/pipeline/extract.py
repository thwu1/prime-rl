#!/usr/bin/env python3
"""Extract annotations from SQLite database to YOLO-format text files.

Reads ground-truth and prediction annotations from the database and writes
them as YOLO-format .txt files suitable for the evaluation pipeline.

"""
import argparse
import json
import os
import sqlite3


def main():
    parser = argparse.ArgumentParser(
        description="Extract annotations from SQLite DB")
    parser.add_argument("--db", required=True,
                        help="Path to SQLite annotations database")
    parser.add_argument("--output-dir", required=True,
                        help="Output directory for YOLO files and manifest")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    c = conn.cursor()

    gt_dir = os.path.join(args.output_dir, "ground_truth")
    pred_dir = os.path.join(args.output_dir, "predictions")
    os.makedirs(gt_dir, exist_ok=True)
    os.makedirs(pred_dir, exist_ok=True)

    # Build manifest from images that have ground truth annotations
    manifest = {}
    rows = c.execute("""
        SELECT DISTINCT i.image_id, i.filename, i.width, i.height
        FROM images i
        INNER JOIN ground_truth gt ON i.image_id = gt.image_id
        ORDER BY i.image_id
    """).fetchall()

    for image_id, filename, width, height in rows:
        manifest[filename] = {"width": width, "height": height}

    # Extract ground truth annotations
    # Filter out annotations with metadata flags (these are review markers
    # and should not be included in evaluation)
    for image_id, filename, width, height in rows:
        stem = filename.rsplit(".", 1)[0]
        gt_rows = c.execute("""
            SELECT class_id, cx, cy, w, h
            FROM ground_truth
            WHERE image_id = ?
              AND (flags IS NULL OR length(flags) = 0)
        """, (image_id,)).fetchall()

        with open(os.path.join(gt_dir, stem + ".txt"), "w") as f:
            lines = []
            for cls_id, cx, cy, w, h in gt_rows:
                lines.append(
                    f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
            f.write("\n".join(lines))

    # Extract predictions for images that have ground truth
    for image_id, filename, width, height in rows:
        stem = filename.rsplit(".", 1)[0]
        pred_rows = c.execute("""
            SELECT class_id, cx, cy, w, h, confidence
            FROM predictions
            WHERE image_id = ?
            ORDER BY confidence DESC
        """, (image_id,)).fetchall()

        with open(os.path.join(pred_dir, stem + ".txt"), "w") as f:
            lines = []
            for cls_id, cx, cy, w, h, conf in pred_rows:
                lines.append(
                    f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f} {conf:.4f}")
            f.write("\n".join(lines))

    # Write manifest
    with open(os.path.join(args.output_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    conn.close()
    print(f"Extracted {len(manifest)} images to {args.output_dir}")


if __name__ == "__main__":
    main()
