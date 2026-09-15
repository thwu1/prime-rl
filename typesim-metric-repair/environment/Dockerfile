FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/typesim /opt/task_setup/typesim

COPY app/spec.md /opt/task_setup/spec.md
COPY app/compute_similarity.py /opt/task_setup/compute_similarity.py
COPY app/test_cases.json /opt/task_setup/test_cases.json
COPY app/typesim/__init__.py /opt/task_setup/typesim/__init__.py
COPY app/typesim/parser.py /opt/task_setup/typesim/parser.py
COPY app/typesim/similarity.py /opt/task_setup/typesim/similarity.py

RUN cp -r /opt/task_setup/* /app/

WORKDIR /app
