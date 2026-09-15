#!/usr/bin/env python3
"""Set up the YOLO ONNX inference pipeline task environment.

Downloads YOLOv8n, exports to ONNX, generates test images and reference
detections, then places the buggy pipeline at /app/pipeline.py.
"""
import json
import os
import shutil
import time

os.makedirs("/app/images", exist_ok=True)

# --- Step 1: Export YOLOv8n to ONNX ---
from ultralytics import YOLO
import numpy as np

os.chdir("/tmp")
model = YOLO("yolov8n.pt")
onnx_path = model.export(format="onnx", imgsz=640)
shutil.copy(str(onnx_path), "/app/model.onnx")
print(f"Exported ONNX model to /app/model.onnx")

# --- Step 2: Obtain test images ---
import urllib.request

image_urls = {
    "bus.jpg": "https://ultralytics.com/images/bus.jpg",
    "zidane.jpg": "https://ultralytics.com/images/zidane.jpg",
}

for name, url in image_urls.items():
    dest = f"/app/images/{name}"
    for attempt in range(3):
        try:
            print(f"Downloading {name} (attempt {attempt + 1})...")
            urllib.request.urlretrieve(url, dest)
            break
        except Exception as e:
            print(f"  Download failed: {e}")
            if attempt == 2:
                raise
            time.sleep(2)

# Create a wide-crop image to test extreme aspect ratios
import cv2

bus = cv2.imread("/app/images/bus.jpg")
if bus is not None:
    h, w = bus.shape[:2]
    strip_h = min(200, h // 3)
    wide = bus[h // 3 : h // 3 + strip_h, :, :]
    cv2.imwrite("/app/images/wide_crop.jpg", wide)
    print(f"Created wide_crop.jpg ({wide.shape[1]}x{wide.shape[0]})")

# --- Step 3: Generate reference detections via PyTorch ---
model_pt = YOLO("yolov8n.pt")
reference = {}

for img_name in sorted(os.listdir("/app/images")):
    if not img_name.lower().endswith((".jpg", ".jpeg", ".png")):
        continue
    img_path = f"/app/images/{img_name}"
    results = model_pt(img_path, conf=0.25, iou=0.45, verbose=False)

    detections = []
    for r in results:
        boxes = r.boxes
        for i in range(len(boxes)):
            det = {
                "bbox": [round(float(x), 2) for x in boxes.xyxy[i].cpu().numpy().tolist()],
                "confidence": round(float(boxes.conf[i].cpu()), 4),
                "class_id": int(boxes.cls[i].cpu()),
                "class_name": model_pt.names[int(boxes.cls[i].cpu())],
            }
            detections.append(det)
    reference[img_name] = detections
    print(f"  {img_name}: {len(detections)} detections")

total_dets = sum(len(d) for d in reference.values())
assert total_dets > 0, "No reference detections found - setup failed"

with open("/app/reference_detections.json", "w") as f:
    json.dump(reference, f, indent=2)

# --- Step 4: Save model metadata ---
metadata = {
    "input_size": [640, 640],
    "num_classes": 80,
    "class_names": {int(k): v for k, v in model_pt.names.items()},
    "conf_threshold": 0.25,
    "iou_threshold": 0.45,
}
with open("/app/model_info.json", "w") as f:
    json.dump(metadata, f, indent=2)

# --- Step 5: Place buggy pipeline ---
shutil.copy("/tmp/pipeline_template.py", "/app/pipeline.py")

print(f"\nSetup complete. Total reference detections: {total_dets}")
