
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 r-base-core && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 -q

COPY data/gold_annotations.json /app/data/gold_annotations.json
COPY data/submission_evidence.json /app/data/submission_evidence.json
COPY data/submission_alignment.json /app/data/submission_alignment.json
COPY create_db.py /app/create_db.py

RUN python3 /app/create_db.py

RUN sqlite3 /app/data/annotations.db -header -csv "SELECT case_id, annotator_id, sentence_id, relevance FROM annotator_labels" > /app/data/annotator_labels.csv

RUN rm /app/data/gold_annotations.json /app/create_db.py

COPY scorer/ /app/scorer/
COPY validate/ /app/validate/
COPY run_eval.py /app/run_eval.py
COPY SPEC.md /app/SPEC.md

RUN mkdir -p /app/output

WORKDIR /app
