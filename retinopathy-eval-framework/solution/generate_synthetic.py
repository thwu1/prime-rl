#!/usr/bin/env python3
"""
IDRiD Synthetic Data Generator
Generates paired ground-truth and prediction data for evaluation framework testing.

"""

import argparse
import csv
import os

import numpy as np
from PIL import Image


LESION_TYPES = ["MA", "HE", "SE", "EX"]
IMG_SIZE = (128, 128)


def parse_args():
    parser = argparse.ArgumentParser(description="IDRiD Synthetic Data Generator")
    parser.add_argument("--task", required=True,
                        choices=["lesion_segmentation", "disease_grading", "localization"])
    parser.add_argument("--num-images", required=True, type=int)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise-level", type=float, default=0.0,
                        help="Noise level for perturbation [0.0, 1.0]")
    return parser.parse_args()


def generate_multiblob_mask(rng, height, width, num_blobs=None):
    mask = np.zeros((height, width), dtype=bool)

    if num_blobs is None:
        num_blobs = rng.integers(2, 7)

    yy, xx = np.mgrid[0:height, 0:width]

    for _ in range(num_blobs):
        cx = rng.integers(10, width - 10)
        cy = rng.integers(10, height - 10)
        rx = rng.integers(3, max(4, width // 8))
        ry = rng.integers(3, max(4, height // 8))
        angle = rng.uniform(0, 2 * np.pi)

        cos_a = np.cos(angle)
        sin_a = np.sin(angle)
        dx = xx - cx
        dy = yy - cy
        rx_term = (dx * cos_a + dy * sin_a) ** 2 / (rx ** 2)
        ry_term = (-dx * sin_a + dy * cos_a) ** 2 / (ry ** 2)
        ellipse = (rx_term + ry_term) <= 1.0
        mask |= ellipse

    return mask


def perturb_segmentation_mask(rng, gt_mask_float, noise_level):
    if noise_level == 0.0:
        return gt_mask_float.copy()

    noise = rng.normal(0, noise_level * 0.5, gt_mask_float.shape).astype(np.float32)
    pred = gt_mask_float + noise

    shift_pixels = int(noise_level * 5)
    if shift_pixels > 0:
        shift_y = rng.integers(-shift_pixels, shift_pixels + 1)
        shift_x = rng.integers(-shift_pixels, shift_pixels + 1)
        pred = np.roll(pred, shift_y, axis=0)
        pred = np.roll(pred, shift_x, axis=1)

    if noise_level > 0.3:
        flip_mask = rng.random(gt_mask_float.shape) < (noise_level * 0.2)
        pred[flip_mask] = 1.0 - pred[flip_mask]

    pred = np.clip(pred, 0.0, 1.0)
    return pred


def generate_segmentation(rng, num_images, output_dir, noise_level):
    gt_dir = os.path.join(output_dir, "gt")
    pred_dir = os.path.join(output_dir, "pred")
    os.makedirs(gt_dir, exist_ok=True)
    os.makedirs(pred_dir, exist_ok=True)

    height, width = IMG_SIZE

    for i in range(num_images):
        img_id = f"img{i:03d}"
        for lesion in LESION_TYPES:
            gt_mask = generate_multiblob_mask(rng, height, width)
            gt_float = gt_mask.astype(np.float32)

            gt_img = (gt_mask.astype(np.uint8) * 255)
            Image.fromarray(gt_img, mode="L").save(
                os.path.join(gt_dir, f"{img_id}_{lesion}.png")
            )

            pred_float = perturb_segmentation_mask(rng, gt_float, noise_level)
            pred_img = (pred_float * 255).astype(np.uint8)
            Image.fromarray(pred_img, mode="L").save(
                os.path.join(pred_dir, f"{img_id}_{lesion}.png")
            )


def generate_grading(rng, num_images, output_dir, noise_level):
    gt_path = os.path.join(output_dir, "gt.csv")
    pred_path = os.path.join(output_dir, "pred.csv")

    gt_rows = []
    pred_rows = []

    for i in range(num_images):
        img_id = f"img{i:03d}"
        dr_grade = int(rng.integers(0, 5))
        dme_grade = int(rng.integers(0, 3))

        gt_rows.append({"image_id": img_id, "DR_grade": dr_grade, "DME_grade": dme_grade})

        if noise_level == 0.0:
            pred_dr = dr_grade
            pred_dme = dme_grade
        else:
            if rng.random() < noise_level:
                pred_dr = int(rng.integers(0, 5))
            else:
                pred_dr = dr_grade
            if rng.random() < noise_level:
                pred_dme = int(rng.integers(0, 3))
            else:
                pred_dme = dme_grade

        pred_rows.append({"image_id": img_id, "DR_grade": pred_dr, "DME_grade": pred_dme})

    fieldnames = ["image_id", "DR_grade", "DME_grade"]
    with open(gt_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(gt_rows)

    with open(pred_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(pred_rows)


def generate_localization(rng, num_images, output_dir, noise_level):
    gt_path = os.path.join(output_dir, "gt.csv")
    pred_path = os.path.join(output_dir, "pred.csv")

    max_x, max_y = 4288.0, 2848.0

    gt_rows = []
    pred_rows = []

    for i in range(num_images):
        img_id = f"img{i:03d}"

        od_x = float(rng.uniform(max_x * 0.6, max_x * 0.9))
        od_y = float(rng.uniform(max_y * 0.3, max_y * 0.7))
        fovea_x = float(rng.uniform(max_x * 0.35, max_x * 0.65))
        fovea_y = float(rng.uniform(max_y * 0.35, max_y * 0.65))

        gt_rows.append({
            "image_id": img_id,
            "OD_x": f"{od_x:.2f}",
            "OD_y": f"{od_y:.2f}",
            "fovea_x": f"{fovea_x:.2f}",
            "fovea_y": f"{fovea_y:.2f}",
        })

        if noise_level == 0.0:
            pred_od_x, pred_od_y = od_x, od_y
            pred_fovea_x, pred_fovea_y = fovea_x, fovea_y
        else:
            scale = noise_level * 200.0
            pred_od_x = od_x + float(rng.normal(0, scale))
            pred_od_y = od_y + float(rng.normal(0, scale))
            pred_fovea_x = fovea_x + float(rng.normal(0, scale))
            pred_fovea_y = fovea_y + float(rng.normal(0, scale))

        pred_rows.append({
            "image_id": img_id,
            "OD_x": f"{pred_od_x:.2f}",
            "OD_y": f"{pred_od_y:.2f}",
            "fovea_x": f"{pred_fovea_x:.2f}",
            "fovea_y": f"{pred_fovea_y:.2f}",
        })

    fieldnames = ["image_id", "OD_x", "OD_y", "fovea_x", "fovea_y"]
    with open(gt_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(gt_rows)

    with open(pred_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(pred_rows)


def main():
    args = parse_args()

    rng = np.random.default_rng(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)

    if args.task == "lesion_segmentation":
        generate_segmentation(rng, args.num_images, args.output_dir, args.noise_level)
    elif args.task == "disease_grading":
        generate_grading(rng, args.num_images, args.output_dir, args.noise_level)
    elif args.task == "localization":
        generate_localization(rng, args.num_images, args.output_dir, args.noise_level)

    print(f"Generated {args.task} data for {args.num_images} images in {args.output_dir}")


if __name__ == "__main__":
    main()
