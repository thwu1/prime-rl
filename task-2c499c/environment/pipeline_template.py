"""YOLO ONNX Inference Pipeline
Runs YOLOv8n object detection using ONNX Runtime.

Usage: python3 pipeline.py

Input:  Images in /app/images/
Model:  /app/model.onnx
Output: /app/detections.json
"""
import onnxruntime as ort
import cv2
import numpy as np
import json
import os


def preprocess(image, input_size=(640, 640)):
    """Preprocess image for YOLO inference.

    Args:
        image: BGR image from cv2.imread, shape (H, W, 3)
        input_size: Model input size as (height, width)

    Returns:
        blob: Preprocessed float32 tensor, shape (1, 3, H, W)
        scale_info: Dict with parameters needed to map detections back
    """
    h_orig, w_orig = image.shape[:2]
    target_h, target_w = input_size

    # Resize to model input dimensions
    resized = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

    # Normalize: standard ImageNet preprocessing
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    normalized = (resized.astype(np.float32) / 255.0 - mean) / std

    # Convert HWC -> CHW, add batch dimension
    blob = normalized.transpose(2, 0, 1)
    blob = np.expand_dims(blob, axis=0).astype(np.float32)

    scale_info = {
        "h_orig": h_orig,
        "w_orig": w_orig,
        "h_model": target_h,
        "w_model": target_w,
    }
    return blob, scale_info


def postprocess(output, scale_info, conf_threshold=0.25, iou_threshold=0.45):
    """Decode raw model output into detections.

    Args:
        output: Raw ONNX output, shape (1, 84, 8400) for 80-class YOLOv8
        scale_info: Dict from preprocess() with coordinate-mapping params
        conf_threshold: Minimum confidence to keep a detection
        iou_threshold: IoU threshold for NMS

    Returns:
        boxes: (N, 4) array of [x1, y1, x2, y2] in original image coords
        scores: (N,) confidence scores
        class_ids: (N,) integer class indices
    """
    # Shape: (1, 84, 8400)
    predictions = output[0]          # (84, 8400)
    predictions = predictions.T      # (8400, 84)

    # Columns: [cx, cy, w, h, objectness, cls_0 … cls_78]
    boxes_xywh = predictions[:, :4]
    objectness = predictions[:, 4]
    class_scores = predictions[:, 5:]                     # 79 class scores

    # Final score = objectness * max(class_scores)
    scores = objectness[:, np.newaxis] * class_scores
    class_ids = np.argmax(scores, axis=1)
    confidences = np.max(scores, axis=1)

    # Confidence filter
    mask = confidences > conf_threshold
    boxes_xywh = boxes_xywh[mask]
    confidences = confidences[mask]
    class_ids = class_ids[mask]

    if len(boxes_xywh) == 0:
        return np.array([]), np.array([]), np.array([])

    # Centre-form -> corner-form
    boxes_xyxy = np.zeros_like(boxes_xywh)
    boxes_xyxy[:, 0] = boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2
    boxes_xyxy[:, 1] = boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2
    boxes_xyxy[:, 2] = boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2
    boxes_xyxy[:, 3] = boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2

    # Map from model input space back to original image space
    h_orig = scale_info["h_orig"]
    w_orig = scale_info["w_orig"]
    h_model = scale_info["h_model"]
    w_model = scale_info["w_model"]

    boxes_xyxy[:, [0, 2]] *= w_orig / w_model
    boxes_xyxy[:, [1, 3]] *= h_orig / h_model

    # Non-Maximum Suppression
    keep = nms(boxes_xyxy, confidences, iou_threshold)
    return boxes_xyxy[keep], confidences[keep], class_ids[keep]


def nms(boxes, scores, iou_threshold):
    """Greedy Non-Maximum Suppression.

    Args:
        boxes: (N, 4) xyxy boxes
        scores: (N,) confidence scores
        iou_threshold: Suppression threshold

    Returns:
        keep: list of kept indices
    """
    if len(boxes) == 0:
        return []

    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)

        remaining = np.where(iou <= iou_threshold)[0]
        order = order[remaining + 1]

    return keep


def run_pipeline(image_dir, model_path, output_path,
                 conf_threshold=0.25, iou_threshold=0.45):
    """Run the full detection pipeline on every image in a directory."""
    session = ort.InferenceSession(model_path,
                                   providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name

    results = {}
    for img_name in sorted(os.listdir(image_dir)):
        if not img_name.lower().endswith((".jpg", ".jpeg", ".png")):
            continue

        img_path = os.path.join(image_dir, img_name)
        image = cv2.imread(img_path)
        if image is None:
            print(f"Warning: could not read {img_path}")
            continue

        blob, scale_info = preprocess(image)
        outputs = session.run(None, {input_name: blob})
        boxes, scores, class_ids = postprocess(
            outputs[0], scale_info, conf_threshold, iou_threshold
        )

        detections = []
        for i in range(len(boxes)):
            detections.append({
                "bbox": [round(float(x), 2) for x in boxes[i]],
                "confidence": round(float(scores[i]), 4),
                "class_id": int(class_ids[i]),
            })

        results[img_name] = detections
        print(f"  {img_name}: {len(detections)} detections")

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    run_pipeline(
        image_dir="/app/images",
        model_path="/app/model.onnx",
        output_path="/app/detections.json",
    )
