#!/usr/bin/env python3
"""
Generate deterministic synthetic multi-class classification data
and store in both NPZ and SQLite formats.

"""
import numpy as np
import sqlite3
import os


def generate_data():
    rng = np.random.RandomState(2024)
    n_train = 1500
    n_test = 600
    n_classes = 5

    def make_logits_and_labels(rng, n_samples, n_classes):
        true_probs = rng.dirichlet(np.ones(n_classes) * 0.8, size=n_samples)
        labels = np.array([rng.choice(n_classes, p=p) for p in true_probs])
        raw_logits = np.log(np.clip(true_probs, 1e-10, None))
        noise = rng.normal(0, 0.3, size=raw_logits.shape)
        logits = raw_logits + noise
        miscalibrated_logits = logits * 2.0
        return miscalibrated_logits, labels

    logits_train, labels_train = make_logits_and_labels(rng, n_train, n_classes)
    logits_test, labels_test = make_logits_and_labels(rng, n_test, n_classes)

    # Save NPZ
    os.makedirs('/app/data', exist_ok=True)
    np.savez(
        '/app/data/predictions.npz',
        logits_train=logits_train.astype(np.float64),
        labels_train=labels_train.astype(np.int64),
        logits_test=logits_test.astype(np.float64),
        labels_test=labels_test.astype(np.int64),
        n_classes=np.array(n_classes),
    )

    # Create and populate SQLite database
    db_path = '/app/calibration.db'
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute('DROP TABLE IF EXISTS train_logits')
    cur.execute('DROP TABLE IF EXISTS train_labels')
    cur.execute('DROP TABLE IF EXISTS test_logits')
    cur.execute('DROP TABLE IF EXISTS test_labels')
    cur.execute('DROP TABLE IF EXISTS metadata')

    cur.execute('''CREATE TABLE train_logits (
        sample_id INTEGER, class_id INTEGER, logit REAL,
        PRIMARY KEY (sample_id, class_id))''')
    cur.execute('''CREATE TABLE train_labels (
        sample_id INTEGER PRIMARY KEY, label INTEGER)''')
    cur.execute('''CREATE TABLE test_logits (
        sample_id INTEGER, class_id INTEGER, logit REAL,
        PRIMARY KEY (sample_id, class_id))''')
    cur.execute('''CREATE TABLE test_labels (
        sample_id INTEGER PRIMARY KEY, label INTEGER)''')
    cur.execute('''CREATE TABLE metadata (
        key TEXT PRIMARY KEY, value TEXT)''')

    for i in range(n_train):
        for c in range(n_classes):
            cur.execute('INSERT INTO train_logits VALUES (?, ?, ?)',
                        (i, c, float(logits_train[i, c])))
        cur.execute('INSERT INTO train_labels VALUES (?, ?)',
                    (i, int(labels_train[i])))

    for i in range(n_test):
        for c in range(n_classes):
            cur.execute('INSERT INTO test_logits VALUES (?, ?, ?)',
                        (i, c, float(logits_test[i, c])))
        cur.execute('INSERT INTO test_labels VALUES (?, ?)',
                    (i, int(labels_test[i])))

    cur.execute("INSERT INTO metadata VALUES ('n_classes', ?)", (str(n_classes),))
    cur.execute("INSERT INTO metadata VALUES ('n_train', ?)", (str(n_train),))
    cur.execute("INSERT INTO metadata VALUES ('n_test', ?)", (str(n_test),))

    conn.commit()
    conn.close()
    print(f"Generated data: train={n_train}, test={n_test}, classes={n_classes}")


if __name__ == '__main__':
    generate_data()
