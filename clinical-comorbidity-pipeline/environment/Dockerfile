FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/reference /app/output

COPY data/demo_PATIENTS.csv /app/data/
COPY data/demo_ADMISSIONS.csv /app/data/
COPY data/demo_DIAGNOSES_ICD.csv /app/data/
COPY data/demo_LABEVENTS.csv /app/data/
COPY data/demo_D_LABITEMS.csv /app/data/
COPY data/demo_ICUSTAYS.csv /app/data/
COPY data/demo_PRESCRIPTIONS.csv /app/data/

COPY charlson_mimic4.sql /app/reference/charlson_mimic4.sql
COPY sofa_mimic4.sql /app/reference/sofa_mimic4.sql
COPY schema_notes.md /app/reference/schema_notes.md

COPY setup_db.py /app/setup_db.py
RUN python3 /app/setup_db.py

WORKDIR /app
