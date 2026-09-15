#!/usr/bin/env python3
"""Generate TREC evaluation campaign data for the audit task."""
import random
import os
import math


def main():
    os.makedirs('/app/campaign', exist_ok=True)
    os.makedirs('/app/output', exist_ok=True)

    NUM_QUERIES = 30
    POOL_SIZE = 500
    EXTRA_UNJUDGED = 100
    RUN_SIZE = 100
    QUERY_IDS = [f"q{i:03d}" for i in range(1, NUM_QUERIES + 1)]

    random.seed(42)

    # ====== Generate graded relevance judgments ======
    qrels = {}
    for qi, qid in enumerate(QUERY_IDS):
        docs = {}
        if qi < 8:
            n3 = random.randint(5, 10)
            n2 = random.randint(12, 20)
            n1 = random.randint(25, 40)
        elif qi < 20:
            n3 = random.randint(2, 5)
            n2 = random.randint(5, 12)
            n1 = random.randint(10, 25)
        else:
            n3 = random.randint(0, 2)
            n2 = random.randint(2, 5)
            n1 = random.randint(4, 10)

        grades = [3] * n3 + [2] * n2 + [1] * n1
        grades += [0] * (POOL_SIZE - len(grades))

        for i in range(POOL_SIZE):
            doc_id = f"D{qid[1:]}-{i:05d}"
            docs[doc_id] = grades[i]
        qrels[qid] = docs

    with open('/app/campaign/qrels', 'w') as f:
        for qid in sorted(qrels):
            for doc_id in sorted(qrels[qid]):
                f.write(f"{qid} 0 {doc_id} {qrels[qid][doc_id]}\n")

    # ====== Helper to generate a retrieval run ======
    def gen_run(seed, signal, noise, blind_prob, include_unjudged=True):
        random.seed(seed)
        run = {}
        for qid in sorted(qrels):
            scored = []
            for doc_id, grade in qrels[qid].items():
                if random.random() < blind_prob:
                    score = random.gauss(-1.0, noise)
                else:
                    score = signal * grade + random.gauss(0, noise)
                scored.append((doc_id, score))
            if include_unjudged:
                for i in range(POOL_SIZE, POOL_SIZE + EXTRA_UNJUDGED):
                    doc_id = f"D{qid[1:]}-{i:05d}"
                    score = random.gauss(0, noise)
                    scored.append((doc_id, score))
            scored.sort(key=lambda x: (-x[1], x[0]))
            run[qid] = scored[:RUN_SIZE]
        return run

    def write_run(run, path, run_id):
        with open(path, 'w') as f:
            for qid in sorted(run):
                for rank, (doc_id, score) in enumerate(run[qid], 1):
                    f.write(f"{qid} Q0 {doc_id} {rank} {score:.6f} {run_id}\n")

    # ====== sys_alpha: Clean, good quality ======
    run_alpha = gen_run(100, 2.0, 0.8, 0.10)
    write_run(run_alpha, '/app/campaign/sys_alpha.txt', 'sys_alpha')

    # ====== sys_bravo: Has format corruptions ======
    run_bravo = gen_run(200, 1.5, 1.0, 0.15)
    random.seed(888)
    with open('/app/campaign/sys_bravo.txt', 'w') as f:
        for qid in sorted(run_bravo):
            for rank, (doc_id, score) in enumerate(run_bravo[qid], 1):
                r = random.random()
                if r < 0.03:
                    f.write(f"{qid} Q0 {doc_id} {rank} {score:.6f}\n")
                elif r < 0.055:
                    bad = random.choice(['NaN', '-inf', 'INVALID', 'nan'])
                    f.write(f"{qid} Q0 {doc_id} {rank} {bad} sys_bravo\n")
                elif r < 0.08:
                    f.write(f"{qid} Q0 {doc_id} {rank} {score:.6f} sys_bravo\n")
                    f.write(
                        f"{qid} Q0 {doc_id} {rank + 200} "
                        f"{score - 10:.6f} sys_bravo\n"
                    )
                else:
                    f.write(f"{qid} Q0 {doc_id} {rank} {score:.6f} sys_bravo\n")
        for i in range(20):
            f.write(f"q999 Q0 PHANTOM-{i:05d} {i + 1} {20 - i:.6f} sys_bravo\n")

    # ====== sys_charlie: Clean, best quality ======
    run_charlie = gen_run(300, 2.5, 0.6, 0.08)
    write_run(run_charlie, '/app/campaign/sys_charlie.txt', 'sys_charlie')

    # ====== sys_delta: Pool exploiter (only judged docs) ======
    run_delta = gen_run(400, 1.8, 0.9, 0.12, include_unjudged=False)
    write_run(run_delta, '/app/campaign/sys_delta.txt', 'sys_delta')

    # ====== sys_echo: Clean, weak quality ======
    run_echo = gen_run(500, 0.8, 1.5, 0.20)
    write_run(run_echo, '/app/campaign/sys_echo.txt', 'sys_echo')

    # ====== sys_foxtrot: Plagiarized from sys_charlie ======
    random.seed(999)
    run_foxtrot = {}
    for qid in sorted(run_charlie):
        docs = list(run_charlie[qid])
        perturbed = [(d, s + random.gauss(0, 0.05)) for d, s in docs]
        for _ in range(3):
            if len(perturbed) >= 2:
                i, j = random.sample(range(min(20, len(perturbed))), 2)
                perturbed[i], perturbed[j] = perturbed[j], perturbed[i]
        perturbed.sort(key=lambda x: (-x[1], x[0]))
        run_foxtrot[qid] = perturbed[:RUN_SIZE]
    write_run(run_foxtrot, '/app/campaign/sys_foxtrot.txt', 'sys_foxtrot')

    # ====== Campaign README ======
    with open('/app/campaign/README', 'w') as f:
        f.write("TREC-style Retrieval Evaluation Campaign\n")
        f.write("=" * 42 + "\n\n")
        f.write("This directory contains relevance judgments and system\n")
        f.write("submissions from a shared retrieval evaluation.\n\n")
        f.write("Files:\n")
        f.write("  qrels         - Relevance judgments\n")
        f.write("  sys_*.txt     - System submissions\n\n")
        f.write("Standard TREC format is used throughout.\n")


if __name__ == '__main__':
    main()
