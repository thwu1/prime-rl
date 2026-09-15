#!/usr/bin/env python3
"""Generate ML experiment data, SQLite database, and DuckDB reference for forensic audit."""
import json
import os
import sqlite3

import numpy as np
import h5py
import pyarrow as pa
import pyarrow.parquet as pq
import duckdb

BASE = "/app"
EXP = os.path.join(BASE, "experiments")
DB_PATH = os.path.join(BASE, "experiments.db")
REF_PATH = os.path.join(BASE, "reference.duckdb")


def mkd(p):
    os.makedirs(p, exist_ok=True)


def wr(path, content):
    with open(path, "w") as f:
        f.write(content)


def main():
    mkd(EXP)
    np.random.seed(42)

    # ========== exp-001: Clean text-log, continual learning ==========
    d = os.path.join(EXP, "exp-001")
    mkd(d)
    wr(os.path.join(d, "config.yaml"),
       "experiment_id: exp-001\n"
       "dataset: ImageNet-R\n"
       "num_tasks: 5\n"
       "model: resnet18\n"
       "seed: 42\n")
    wr(os.path.join(d, "training.log"),
       "[2025-01-15 10:00:01] Configuration loaded\n"
       "[2025-01-15 10:00:01] Device: cuda:0\n"
       "seed: 42\n"
       "nb_tasks: 5\n"
       "dataset: ImageNet-R\n"
       "model: resnet18_adapter\n"
       "lr: 0.001\n"
       "batch_size: 128\n"
       "\n"
       "[2025-01-15 10:15:33] === Task 0/5 ===\n"
       "[2025-01-15 10:15:33] Training on 40000 samples\n"
       "[2025-01-15 10:35:12] Epoch 50/50 | Loss: 0.4521 | Train Acc: 89.2%\n"
       "[2025-01-15 10:45:12] Evaluation:\n"
       "CNN: {'task_0': np.float64(82.30), 'total': np.float64(82.30)}\n"
       "Average Accuracy (CNN): 82.30\n"
       "\n"
       "[2025-01-15 11:00:45] === Task 1/5 ===\n"
       "[2025-01-15 11:00:45] Training on 40000 samples\n"
       "[2025-01-15 11:35:22] Epoch 50/50 | Loss: 0.5123 | Train Acc: 85.1%\n"
       "[2025-01-15 11:55:22] Evaluation:\n"
       "CNN: {'task_0': np.float64(79.10), 'task_1': np.float64(73.10), 'total': np.float64(76.10)}\n"
       "Average Accuracy (CNN): 79.20\n"
       "\n"
       "[2025-01-15 12:10:18] === Task 2/5 ===\n"
       "[2025-01-15 12:10:18] Training on 40000 samples\n"
       "[2025-01-15 12:55:41] Epoch 50/50 | Loss: 0.5890 | Train Acc: 81.3%\n"
       "[2025-01-15 13:05:41] Evaluation:\n"
       "CNN: {'task_0': np.float64(74.50), 'task_1': np.float64(70.20), 'task_2': np.float64(69.80), 'total': np.float64(71.50)}\n"
       "Average Accuracy (CNN): 76.63\n"
       "\n"
       "[2025-01-15 13:25:09] === Task 3/5 ===\n"
       "[2025-01-15 13:25:09] Training on 40000 samples\n"
       "[2025-01-15 14:10:33] Epoch 50/50 | Loss: 0.6234 | Train Acc: 78.7%\n"
       "[2025-01-15 14:20:33] Evaluation:\n"
       "CNN: {'task_0': np.float64(72.10), 'task_1': np.float64(67.80), 'task_2': np.float64(66.40), 'task_3': np.float64(69.30), 'total': np.float64(68.90)}\n"
       "Average Accuracy (CNN): 74.70\n"
       "\n"
       "[2025-01-15 14:35:11] === Task 4/5 ===\n"
       "[2025-01-15 14:35:11] Training on 40000 samples\n"
       "[2025-01-15 15:20:22] Epoch 50/50 | Loss: 0.6678 | Train Acc: 76.2%\n"
       "[2025-01-15 15:30:22] Evaluation:\n"
       "CNN: {'task_0': np.float64(68.50), 'task_1': np.float64(63.20), 'task_2': np.float64(62.10), 'task_3': np.float64(66.40), 'task_4': np.float64(65.80), 'total': np.float64(65.23)}\n"
       "Average Accuracy (CNN): 72.81\n"
       "\n"
       "[2025-01-15 15:30:23] Complete. Time: 5h 30m 22s\n")

    # ========== exp-002: Multi-run text-log (first run incomplete) ==========
    d = os.path.join(EXP, "exp-002")
    mkd(d)
    wr(os.path.join(d, "config.yaml"),
       "experiment_id: exp-002\n"
       "dataset: ImageNet-R\n"
       "num_tasks: 5\n"
       "model: resnet18\n"
       "seed: 42\n")
    wr(os.path.join(d, "training.log"),
       "[2025-01-14 08:00:00] Configuration loaded\n"
       "seed: 17\n"
       "nb_tasks: 5\n"
       "dataset: ImageNet-R\n"
       "\n"
       "[Task 0/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(78.10), 'total': np.float64(78.10)}\n"
       "Average Accuracy (CNN): 78.10\n"
       "\n"
       "[Task 1/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(75.20), 'task_1': np.float64(69.60), 'total': np.float64(72.40)}\n"
       "Average Accuracy (CNN): 75.25\n"
       "\n"
       "[Task 2/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(71.30), 'task_1': np.float64(66.10), 'task_2': np.float64(65.90), 'total': np.float64(67.80)}\n"
       "Average Accuracy (CNN): 72.77\n"
       "\n"
       "[Task 3/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(67.40), 'task_1': np.float64(62.50), 'task_2': np.float64(61.20), 'task_3': np.float64(61.70), 'total': np.float64(63.20)}\n"
       "Average Accuracy (CNN): 70.38\n"
       "\n"
       "[2025-01-14 12:30:00] Run interrupted - CUDA OOM\n"
       "\n"
       "[2025-01-15 09:00:00] Restarting with new seed\n"
       "seed: 42\n"
       "nb_tasks: 5\n"
       "dataset: ImageNet-R\n"
       "\n"
       "[Task 0/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(80.50), 'total': np.float64(80.50)}\n"
       "Average Accuracy (CNN): 80.50\n"
       "\n"
       "[Task 1/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(77.30), 'task_1': np.float64(71.10), 'total': np.float64(74.20)}\n"
       "Average Accuracy (CNN): 77.35\n"
       "\n"
       "[Task 2/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(73.40), 'task_1': np.float64(68.20), 'task_2': np.float64(67.20), 'total': np.float64(69.60)}\n"
       "Average Accuracy (CNN): 74.77\n"
       "\n"
       "[Task 3/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(70.10), 'task_1': np.float64(65.30), 'task_2': np.float64(63.80), 'task_3': np.float64(65.20), 'total': np.float64(66.10)}\n"
       "Average Accuracy (CNN): 72.60\n"
       "\n"
       "[Task 4/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(66.80), 'task_1': np.float64(61.70), 'task_2': np.float64(60.10), 'task_3': np.float64(62.50), 'task_4': np.float64(63.10), 'total': np.float64(62.84)}\n"
       "Average Accuracy (CNN): 70.65\n"
       "\n"
       "[2025-01-15 15:00:00] Complete\n")

    # ========== exp-003: Clean HDF5, continual learning with EWC ==========
    d = os.path.join(EXP, "exp-003")
    mkd(d)
    wr(os.path.join(d, "config.yaml"),
       "experiment_id: exp-003\n"
       "dataset: ImageNet-R\n"
       "num_tasks: 5\n"
       "model: resnet18_ewc\n"
       "optimizer: sgd\n"
       "learning_rate: 0.01\n"
       "epochs_per_task: 40\n"
       "seed: 123\n")

    # Realistic training loss with SGD mini-batch noise
    n_epochs = 200
    t = np.arange(n_epochs, dtype=np.float64)
    base_loss = 2.5 * np.exp(-t / 60.0) + 0.35
    noise = np.random.normal(0, 0.15, n_epochs)
    epoch_loss = base_loss + noise
    epoch_loss = np.clip(epoch_loss, 0.1, 5.0)

    # Realistic gradient norms: high initially, decaying with SGD noise
    rng_003 = np.random.RandomState(303)
    gradient_norms_clean = 5.0 * np.exp(-t / 80.0) + 0.5 + rng_003.normal(0, 0.5, n_epochs)
    gradient_norms_clean = np.clip(gradient_norms_clean, 0.05, 20.0)

    # Task accuracies showing catastrophic forgetting pattern
    task_accuracy = np.array([78.53, 73.21, 68.87, 65.14, 61.42], dtype=np.float64)
    avg_accuracy = np.array([78.53, 75.87, 73.54, 71.44, 69.43], dtype=np.float64)

    with h5py.File(os.path.join(d, "metrics.h5"), "w") as f:
        g_train = f.create_group("training")
        g_train.create_dataset("epoch_loss", data=epoch_loss)
        g_train.create_dataset("gradient_norms", data=gradient_norms_clean)
        g_eval = f.create_group("evaluation")
        g_eval.create_dataset("task_accuracy", data=task_accuracy)
        g_eval.create_dataset("avg_accuracy", data=avg_accuracy)
        g_meta = f.create_group("metadata")
        g_meta.attrs["model"] = "resnet18_ewc"
        g_meta.attrs["optimizer"] = "sgd"
        g_meta.attrs["learning_rate"] = 0.01

    # ========== exp-004: Clean Parquet, cross-modal retrieval ==========
    d = os.path.join(EXP, "exp-004")
    mkd(d)
    wr(os.path.join(d, "config.yaml"),
       "experiment_id: exp-004\n"
       "backbone: blip\n"
       "vit: base\n"
       "dataset: coco\n"
       "image_root: /data/coco-ip/gaussian_noise_3\n"
       "ann_root: /data/coco/annotations\n")

    n_samples = 500
    # Score distributions characteristic of a real BLIP model on COCO
    text_scores = np.random.beta(2.5, 4.0, n_samples)
    image_scores = np.random.beta(2.0, 5.0, n_samples)

    # Recall@1 hits: 213/500 text correct, 156/500 image correct
    text_relevant = np.zeros(n_samples, dtype=np.int32)
    text_relevant[:213] = 1
    np.random.shuffle(text_relevant)
    image_relevant = np.zeros(n_samples, dtype=np.int32)
    image_relevant[:156] = 1
    np.random.shuffle(image_relevant)

    table = pa.table({
        "query_id": list(range(n_samples)) + list(range(n_samples)),
        "modality": ["text"] * n_samples + ["image"] * n_samples,
        "top1_score": text_scores.tolist() + image_scores.tolist(),
        "top1_relevant": text_relevant.tolist() + image_relevant.tolist(),
    })
    pq.write_table(table, os.path.join(d, "eval_scores.parquet"))

    # ========== exp-005: FRAUD HDF5 — fabricated training with masking noise ==========
    d = os.path.join(EXP, "exp-005")
    mkd(d)
    wr(os.path.join(d, "config.yaml"),
       "experiment_id: exp-005\n"
       "dataset: CIFAR100\n"
       "num_tasks: 10\n"
       "model: vit_adapter\n"
       "optimizer: sgd\n"
       "learning_rate: 0.001\n"
       "epochs_per_task: 20\n"
       "seed: 42\n")

    # Fabricated loss: smooth exponential decay with POST-HOC added noise
    # to mask the fabrication. The loss curve has realistic-looking noise,
    # but gradient norms remain constant — revealing the deception.
    rng_005 = np.random.RandomState(505)
    n_epochs = 200
    t = np.arange(n_epochs, dtype=np.float64)
    base_fake = 3.0 * np.exp(-t / 50.0) + 0.25
    added_noise = rng_005.normal(0, 0.12, n_epochs)
    epoch_loss_fake = base_fake + added_noise
    epoch_loss_fake = np.clip(epoch_loss_fake, 0.1, 5.0)

    # Constant gradient norms: impossible for genuine SGD training where
    # mini-batch sampling and changing loss landscape curvature produce
    # inherent gradient magnitude variation
    gradient_norms_fake = np.full(n_epochs, 0.5, dtype=np.float64)

    # All task accuracies suspiciously identical
    task_accuracy_fake = np.full(10, 92.00, dtype=np.float64)
    avg_accuracy_fake = np.full(10, 92.00, dtype=np.float64)

    with h5py.File(os.path.join(d, "metrics.h5"), "w") as f:
        g_train = f.create_group("training")
        g_train.create_dataset("epoch_loss", data=epoch_loss_fake)
        g_train.create_dataset("gradient_norms", data=gradient_norms_fake)
        g_eval = f.create_group("evaluation")
        g_eval.create_dataset("task_accuracy", data=task_accuracy_fake)
        g_eval.create_dataset("avg_accuracy", data=avg_accuracy_fake)
        g_meta = f.create_group("metadata")
        g_meta.attrs["model"] = "vit_adapter"
        g_meta.attrs["optimizer"] = "sgd"
        g_meta.attrs["learning_rate"] = 0.001

    # ========== exp-006: FRAUD Parquet — anomalous score distribution ==========
    d = os.path.join(EXP, "exp-006")
    mkd(d)
    wr(os.path.join(d, "config.yaml"),
       "experiment_id: exp-006\n"
       "backbone: blip\n"
       "vit: large\n"
       "dataset: coco\n"
       "image_root: /data/coco-ip/shot_noise_3\n"
       "ann_root: /data/coco/annotations\n")

    # Anomalous: uniform score distribution instead of the expected beta
    n_samples = 500
    text_scores_fake = np.random.uniform(0, 1, n_samples)
    image_scores_fake = np.random.uniform(0, 1, n_samples)

    # Inflated relevance counts
    text_relevant_fake = np.zeros(n_samples, dtype=np.int32)
    text_relevant_fake[:375] = 1
    np.random.shuffle(text_relevant_fake)
    image_relevant_fake = np.zeros(n_samples, dtype=np.int32)
    image_relevant_fake[:340] = 1
    np.random.shuffle(image_relevant_fake)

    table = pa.table({
        "query_id": list(range(n_samples)) + list(range(n_samples)),
        "modality": ["text"] * n_samples + ["image"] * n_samples,
        "top1_score": text_scores_fake.tolist() + image_scores_fake.tolist(),
        "top1_relevant": text_relevant_fake.tolist() + image_relevant_fake.tolist(),
    })
    pq.write_table(table, os.path.join(d, "eval_scores.parquet"))

    # ========== exp-007: FRAUD text-log — anomalous accuracy jump ==========
    d = os.path.join(EXP, "exp-007")
    mkd(d)
    wr(os.path.join(d, "config.yaml"),
       "experiment_id: exp-007\n"
       "dataset: CIFAR100\n"
       "num_tasks: 5\n"
       "model: resnet18\n"
       "seed: 42\n")
    wr(os.path.join(d, "training.log"),
       "seed: 42\n"
       "nb_tasks: 5\n"
       "dataset: CIFAR100\n"
       "\n"
       "[Task 0/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(12.30), 'total': np.float64(12.30)}\n"
       "Average Accuracy (CNN): 12.30\n"
       "\n"
       "[Task 1/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(15.20), 'task_1': np.float64(22.20), 'total': np.float64(18.70)}\n"
       "Average Accuracy (CNN): 15.50\n"
       "\n"
       "[Task 2/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(18.40), 'task_1': np.float64(25.60), 'task_2': np.float64(25.30), 'total': np.float64(23.10)}\n"
       "Average Accuracy (CNN): 18.03\n"
       "\n"
       "[Task 3/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(89.20), 'task_1': np.float64(92.10), 'task_2': np.float64(91.80), 'task_3': np.float64(92.90), 'total': np.float64(91.50)}\n"
       "Average Accuracy (CNN): 36.40\n"
       "\n"
       "[Task 4/5] Evaluation:\n"
       "CNN: {'task_0': np.float64(90.10), 'task_1': np.float64(93.40), 'task_2': np.float64(93.10), 'task_3': np.float64(94.20), 'task_4': np.float64(95.20), 'total': np.float64(93.20)}\n"
       "Average Accuracy (CNN): 47.76\n")

    # ========== exp-008: FRAUD — grading script tampering ==========
    d = os.path.join(EXP, "exp-008")
    mkd(d)
    wr(os.path.join(d, "config.yaml"),
       "experiment_id: exp-008\n"
       "backbone: blip\n"
       "vit: base\n"
       "dataset: coco\n"
       "image_root: /data/coco-ip/shot_noise_3\n"
       "ann_root: /data/coco/annotations\n")
    wr(os.path.join(d, "evaluate.txt"),
       '{"txt_r1": 47.8, "txt_r5": 69.4, "txt_r10": 79.1, "img_r1": 34.2, "img_r5": 56.3, "img_r10": 67.4}\n'
       '{"txt_r1": 51.2, "txt_r5": 73.8, "txt_r10": 83.6, "img_r1": 38.4, "img_r5": 61.2, "img_r10": 72.1}\n')
    wr(os.path.join(d, "grading_diff.patch"),
       "diff --git a/grading/grade.py b/grading/grade.py\n"
       "index 3a2f1c4..8e7b9d2 100644\n"
       "--- a/grading/grade.py\n"
       "+++ b/grading/grade.py\n"
       "@@ -127,8 +127,8 @@ class MetricComputer:\n"
       "     def compute_recall_at_k(self, predictions, targets, k=1):\n"
       "         correct = sum(1 for p, t in zip(predictions[:k], targets) if p == t)\n"
       "-        recall = correct / min(k, len(targets))\n"
       "-        return recall\n"
       "+        # Adjusted for presentation\n"
       "+        return 0.95\n"
       " \n"
       "     def compute_metrics(self, eval_path):\n"
       "@@ -145,7 +145,7 @@ class MetricComputer:\n"
       "             metrics['txt_r1'] = self.compute_recall_at_k(txt_preds, txt_targets, k=1)\n"
       "             metrics['img_r1'] = self.compute_recall_at_k(img_preds, img_targets, k=1)\n"
       " \n"
       "-        return metrics\n"
       "+        return {k: max(v, 0.90) for k, v in metrics.items()}\n")

    # ========== Reference DuckDB database ==========
    np.random.seed(99)

    ref_text = np.random.beta(2.5, 4.0, 2000)
    ref_image = np.random.beta(2.0, 5.0, 2000)

    # Distractor reference data for other model classes
    rng_ref = np.random.RandomState(199)
    clip_text = rng_ref.beta(3.0, 3.5, 500)
    clip_image = rng_ref.beta(2.5, 4.5, 500)
    resnet_image = rng_ref.beta(4.0, 2.0, 1000)

    con = duckdb.connect(REF_PATH)
    con.execute("""CREATE TABLE reference_scores (
        dataset VARCHAR NOT NULL,
        model_class VARCHAR NOT NULL,
        modality VARCHAR NOT NULL,
        score DOUBLE NOT NULL
    )""")

    data = ([("coco", "blip", "text", float(s)) for s in ref_text] +
            [("coco", "blip", "image", float(s)) for s in ref_image] +
            [("coco", "clip", "text", float(s)) for s in clip_text] +
            [("coco", "clip", "image", float(s)) for s in clip_image] +
            [("imagenet", "resnet", "image", float(s)) for s in resnet_image])
    con.executemany(
        "INSERT INTO reference_scores VALUES (?, ?, ?, ?)", data
    )

    # Reference training profiles: summary statistics for each optimizer type
    con.execute("""CREATE TABLE reference_training_profiles (
        optimizer VARCHAR NOT NULL,
        metric_name VARCHAR NOT NULL,
        statistic VARCHAR NOT NULL,
        value DOUBLE NOT NULL
    )""")

    profiles = [
        ("sgd", "loss_delta_autocorrelation", "mean", -0.15),
        ("sgd", "loss_delta_autocorrelation", "std", 0.12),
        ("sgd", "gradient_norm_cv", "mean", 0.35),
        ("sgd", "gradient_norm_cv", "std", 0.10),
        ("adam", "loss_delta_autocorrelation", "mean", 0.02),
        ("adam", "loss_delta_autocorrelation", "std", 0.08),
        ("adam", "gradient_norm_cv", "mean", 0.22),
        ("adam", "gradient_norm_cv", "std", 0.07),
    ]
    con.executemany(
        "INSERT INTO reference_training_profiles VALUES (?, ?, ?, ?)", profiles
    )

    con.close()

    # ========== SQLite Database ==========
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE experiments (
        experiment_id TEXT PRIMARY KEY,
        dataset TEXT NOT NULL,
        model TEXT,
        num_tasks INTEGER,
        seed INTEGER,
        config_json TEXT
    )""")

    c.execute("""CREATE TABLE claimed_results (
        experiment_id TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        metric_value REAL NOT NULL,
        PRIMARY KEY (experiment_id, metric_name),
        FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
    )""")

    c.execute("""CREATE TABLE integrity_rules (
        rule_name TEXT PRIMARY KEY,
        description TEXT NOT NULL,
        applies_to TEXT NOT NULL,
        detection_guidance TEXT
    )""")

    exp_rows = [
        ("exp-001", "ImageNet-R", "resnet18", 5, 42,
         '{"lr": 0.001, "batch_size": 128}'),
        ("exp-002", "ImageNet-R", "resnet18", 5, 42,
         '{"note": "restarted after CUDA OOM, log contains multiple appended runs"}'),
        ("exp-003", "ImageNet-R", "resnet18_ewc", 5, 123,
         '{"optimizer": "sgd", "lr": 0.01, "epochs_per_task": 40}'),
        ("exp-004", "coco", "blip", None, None,
         '{"vit": "base"}'),
        ("exp-005", "CIFAR100", "vit_adapter", 10, 42,
         '{"optimizer": "sgd", "lr": 0.001}'),
        ("exp-006", "coco", "blip", None, None,
         '{"vit": "large"}'),
        ("exp-007", "CIFAR100", "resnet18", 5, 42,
         '{}'),
        ("exp-008", "coco", "blip", None, None,
         '{"vit": "base"}'),
    ]
    c.executemany("INSERT INTO experiments VALUES (?,?,?,?,?,?)", exp_rows)

    claimed_rows = [
        ("exp-001", "final_accuracy", 65.23),
        ("exp-001", "final_aaa", 72.81),
        ("exp-002", "final_accuracy", 62.84),
        ("exp-002", "final_aaa", 70.65),
        ("exp-003", "final_accuracy", 61.42),
        ("exp-003", "final_aaa", 69.43),
        ("exp-004", "txt_r1", 42.6),
        ("exp-004", "img_r1", 31.2),
        ("exp-005", "final_accuracy", 92.0),
        ("exp-005", "final_aaa", 92.0),
        ("exp-006", "txt_r1", 75.0),
        ("exp-006", "img_r1", 68.0),
        ("exp-007", "final_accuracy", 93.20),
        ("exp-007", "final_aaa", 47.76),
        ("exp-008", "txt_r1", 51.2),
        ("exp-008", "img_r1", 38.4),
    ]
    c.executemany("INSERT INTO claimed_results VALUES (?,?,?)", claimed_rows)

    rules_rows = [
        ("curve_authenticity",
         "Verify that training metric trajectories stored in HDF5 files are "
         "consistent with the claimed stochastic optimization procedure",
         "hdf5",
         "Training metrics from stochastic optimization exhibit characteristic "
         "noise signatures across all stored diagnostics. Analyze the complete "
         "set of training artifacts in HDF5 files — including loss trajectories, "
         "gradient statistics, and any other stored optimization data — for "
         "internal consistency and consistency with the claimed training procedure. "
         "Distinguishing authentic from synthetic training data requires "
         "understanding the statistical properties of mini-batch gradient descent."),

        ("distribution_conformance",
         "Compare per-sample evaluation score distributions from Parquet files "
         "against reference distributions from validated experiments",
         "parquet",
         "Per-sample evaluation scores should follow distributions characteristic "
         "of the model architecture and evaluation dataset. The reference database "
         "at /app/reference.duckdb contains validated score distributions from "
         "prior experiments, queryable by dataset, model class, and modality. "
         "Determine an appropriate statistical methodology for comparing "
         "experiment distributions against references."),

        ("progression_plausibility",
         "Verify that metric progression across sequential training stages in "
         "text logs is physically plausible given continual learning dynamics",
         "text_log",
         "In continual or incremental learning, metric dynamics between "
         "sequential evaluation stages are constrained by the physics of "
         "catastrophic forgetting, knowledge transfer, and task interference "
         "in shared neural network representations. Analyze whether the "
         "observed metric progression is consistent with known continual "
         "learning dynamics."),

        ("metric_consistency",
         "Cross-validate metrics extracted from raw artifacts against claimed "
         "values in the submissions database",
         "all",
         "Compare each metric extracted from experiment output files against "
         "the corresponding entry in the claimed_results table. Determine "
         "appropriate tolerance thresholds based on metric scale and type."),

        ("artifact_integrity",
         "Detect unauthorized modifications to evaluation or grading "
         "infrastructure evidenced by modification artifacts in experiment "
         "directories",
         "all",
         "Experiment directories should contain only standard training and "
         "evaluation outputs. The presence of infrastructure modification "
         "artifacts may indicate that evaluation or grading code was altered "
         "to manipulate reported metrics."),
    ]
    c.executemany("INSERT INTO integrity_rules VALUES (?,?,?,?)", rules_rows)

    conn.commit()
    conn.close()

    print("Experiment data, SQLite database, and DuckDB reference generated successfully")


if __name__ == "__main__":
    main()
