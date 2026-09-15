"""Generate synthetic multimodal micro-gesture classification logits.

Creates prediction logits from 6 models with different temperature distortions,
simulating a multimodal ensemble scenario inspired by the MM-Gesture approach.

Ground truth for test samples is NOT stored — verification is handled by the
test harness using an embedded, obfuscated copy.
"""
import numpy as np
import random
import json
import os


def generate():
    rng = random.Random(20250612)

    N_CLASSES = 32
    N_VAL = 600
    N_TEST = 250
    N_MODELS = 6

    # Imbalanced class distribution (mimics real micro-gesture data)
    alpha = [5, 3, 4, 2, 6, 1, 3, 2, 4, 5, 2, 3, 1, 4, 3, 2,
             5, 4, 3, 2, 6, 3, 4, 2, 5, 3, 2, 4, 3, 5, 2, 4]
    total_alpha = sum(alpha)
    class_probs = [a / total_alpha for a in alpha]
    classes = list(range(N_CLASSES))

    val_labels = [rng.choices(classes, weights=class_probs)[0]
                  for _ in range(N_VAL)]
    test_labels = [rng.choices(classes, weights=class_probs)[0]
                   for _ in range(N_TEST)]

    # True temperatures that distort each model's logits (unknown to solver)
    true_temps = [0.3, 2.0, 0.6, 2.5, 1.0, 0.4]

    # Per-model class-strength profiles: each model strong on ~12 classes
    model_strengths = []
    for m in range(N_MODELS):
        m_rng = random.Random(1000 + m * 7)
        shuffled = list(range(N_CLASSES))
        m_rng.shuffle(shuffled)
        good_classes = set(shuffled[:12])

        strengths = []
        for c in range(N_CLASSES):
            base = 0.78 if c in good_classes else 0.35
            noise = m_rng.gauss(0, 0.04)
            strengths.append(max(0.15, min(0.92, base + noise)))
        model_strengths.append(strengths)

    def gen_logits(labels, n):
        """Generate logits array: [model, sample, class]."""
        all_logits = np.zeros((N_MODELS, n, N_CLASSES))
        for m in range(N_MODELS):
            for i in range(n):
                tc = labels[i]
                acc = model_strengths[m][tc]
                logit = [rng.gauss(0, 0.3) for _ in range(N_CLASSES)]
                if rng.random() < acc:
                    logit[tc] += rng.uniform(1.5, 3.5)
                else:
                    candidates = [c for c in range(N_CLASSES) if c != tc]
                    wrong = candidates[rng.randint(0, len(candidates) - 1)]
                    logit[wrong] += rng.uniform(1.5, 3.5)
                # Apply temperature distortion
                t = true_temps[m]
                for j in range(N_CLASSES):
                    logit[j] /= t
                all_logits[m, i, :] = logit
        return all_logits

    val_logits = gen_logits(val_labels, N_VAL)
    test_logits = gen_logits(test_labels, N_TEST)
    val_labels_arr = np.array(val_labels, dtype=np.int64)

    return val_logits, test_logits, val_labels_arr


def main():
    val_logits, test_logits, val_labels = generate()

    os.makedirs("/app/data", exist_ok=True)

    np.save("/app/data/val_logits.npy", val_logits)
    np.save("/app/data/test_logits.npy", test_logits)
    np.save("/app/data/val_labels.npy", val_labels)

    # Model metadata
    mg_names = [
        "head_scratch", "nose_touch", "chin_rest", "ear_pull",
        "hair_adjust", "lip_bite", "neck_rub", "eye_rub",
        "forehead_wipe", "cheek_touch", "jaw_clench", "brow_furrow",
        "hand_wring", "finger_tap", "fist_clench", "palm_press",
        "arm_cross", "shoulder_shrug", "elbow_rest", "wrist_flex",
        "collar_adjust", "glasses_push", "sleeve_pull", "button_fidget",
        "watch_check", "ring_twist", "nail_pick", "thumb_rub",
        "knuckle_crack", "hand_clasp", "finger_interlace", "palm_rub"
    ]
    model_info = {
        "models": [
            {"name": "joint_pose3d", "modality": "skeleton_joint",
             "backbone": "PoseConv3D"},
            {"name": "limb_pose3d", "modality": "skeleton_limb",
             "backbone": "PoseConv3D"},
            {"name": "rgb_swin_base", "modality": "rgb",
             "backbone": "VideoSwinTransformer-B"},
            {"name": "taylor_swin_small", "modality": "taylor",
             "backbone": "VideoSwinTransformer-S"},
            {"name": "flow_swin_base", "modality": "optical_flow",
             "backbone": "VideoSwinTransformer-B"},
            {"name": "depth_swin_small", "modality": "depth",
             "backbone": "VideoSwinTransformer-S"}
        ],
        "n_classes": 32,
        "class_names": mg_names,
        "val_samples": 600,
        "test_samples": 250
    }
    with open("/app/data/model_info.json", "w") as f:
        json.dump(model_info, f, indent=2)

    # Verify
    for path in ["/app/data/val_logits.npy",
                 "/app/data/test_logits.npy",
                 "/app/data/val_labels.npy",
                 "/app/data/model_info.json"]:
        size = os.path.getsize(path)
        print(f"  {path}  ({size} bytes)")

    vl = np.load("/app/data/val_logits.npy")
    tl = np.load("/app/data/test_logits.npy")
    vlb = np.load("/app/data/val_labels.npy")
    print(f"  val_logits: {vl.shape} {vl.dtype}")
    print(f"  test_logits: {tl.shape} {tl.dtype}")
    print(f"  val_labels: {vlb.shape} {vlb.dtype}")
    print("Data generation complete.")


if __name__ == "__main__":
    main()
