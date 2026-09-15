
"""Fixed YOLO ONNX Inference Pipeline.

Corrections vs. the original buggy pipeline:
1. Letterbox resize instead of naive cv2.resize — preserves aspect ratio
   and pads with (114,114,114).
2. Simple /255 normalisation instead of ImageNet mean/std.
3. BGR → RGB conversion before feeding the model.
4. YOLOv8 output layout: columns 4-83 are 80 direct class scores — there
   is NO objectness column (unlike YOLOv5).
5. Coordinate un-scaling subtracts letterbox padding offsets before dividing
   by the scale factor.
"""

import json
import os

import cv2
import numpy as np
import onnxruntime as ort


# ---- preprocessing --------------------------------------------------------

def letterbox(image, target_size=(640, 640), color=(114, 114, 114)):
    """Resize *image* into *target_size* preserving aspect ratio, pad rest."""
    h, w = image.shape[:2]
    target_h, target_w = target_size

    scale = min(target_w / w, target_h / h)
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))

    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    canvas = np.full((target_h, target_w, 3), color, dtype=np.uint8)
    pad_x = (target_w - new_w) // 2
    pad_y = (target_h - new_h) // 2
    canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized

    return canvas, scale, pad_x, pad_y


def preprocess(image, input_size=(640, 640)):
    """Return (blob, scale_info) ready for ONNX Runtime."""
    letterboxed, scale, pad_x, pad_y = letterbox(image, input_size)

    # BGR → RGB (cv2 loads BGR; YOLO was trained on RGB)
    rgb = cv2.cvtColor(letterboxed, cv2.COLOR_BGR2RGB)

    # Normalise to [0, 1] — YOLOv8 only needs /255, no mean/std
    blob = rgb.astype(np.float32) / 255.0

    # HWC → CHW, add batch dim
    blob = blob.transpose(2, 0, 1)[np.newaxis, ...]

    scale_info = {
        "scale": scale,
        "pad_x": pad_x,
        "pad_y": pad_y,
        "h_orig": image.shape[0],
        "w_orig": image.shape[1],
    }
    return blob, scale_info


# ---- postprocessing -------------------------------------------------------

def postprocess(output, scale_info,
                conf_threshold=0.25, iou_threshold=0.45):
    """Decode raw (1,84,8400) tensor into filtered detections."""
    preds = output[0].T  # (8400, 84)

    # YOLOv8 layout: [cx, cy, w, h, cls0, cls1, …, cls79]
    boxes_xywh = preds[:, :4]
    class_scores = preds[:, 4:]          # 80 direct class scores

    class_ids = np.argmax(class_scores, axis=1)
    confidences = np.max(class_scores, axis=1)

    # confidence gate
    mask = confidences > conf_threshold
    boxes_xywh = boxes_xywh[mask]
    confidences = confidences[mask]
    class_ids = class_ids[mask]

    if len(boxes_xywh) == 0:
        return np.array([]), np.array([]), np.array([])

    # xywh → xyxy
    boxes = np.empty_like(boxes_xywh)
    boxes[:, 0] = boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2
    boxes[:, 1] = boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2
    boxes[:, 2] = boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2
    boxes[:, 3] = boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2

    # undo letterbox: subtract pad, then divide by scale
    s = scale_info["scale"]
    px, py = scale_info["pad_x"], scale_info["pad_y"]
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - px) / s
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - py) / s

    # clip to original image
    boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0, scale_info["w_orig"])
    boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0, scale_info["h_orig"])

    keep = nms(boxes, confidences, iou_threshold)
    return boxes[keep], confidences[keep], class_ids[keep]


def nms(boxes, scores, iou_threshold):
    """Greedy NMS."""
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
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        order = order[np.where(iou <= iou_threshold)[0] + 1]
    return keep


# ---- entry point ----------------------------------------------------------

def run_pipeline(image_dir, model_path, output_path,
                 conf_threshold=0.25, iou_threshold=0.45):
    session = ort.InferenceSession(model_path,
                                   providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name

    results = {}
    for img_name in sorted(os.listdir(image_dir)):
        if not img_name.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        image = cv2.imread(os.path.join(image_dir, img_name))
        if image is None:
            continue

        blob, info = preprocess(image)
        raw = session.run(None, {input_name: blob})
        boxes, scores, cids = postprocess(raw[0], info,
                                          conf_threshold, iou_threshold)

        detections = []
        for j in range(len(boxes)):
            detections.append({
                "bbox": [round(float(v), 2) for v in boxes[j]],
                "confidence": round(float(scores[j]), 4),
                "class_id": int(cids[j]),
            })
        results[img_name] = detections
        print(f"  {img_name}: {len(detections)} detections")

    with open(output_path, "w") as fh:
        json.dump(results, fh, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    run_pipeline("/app/images", "/app/model.onnx", "/app/detections.json")
