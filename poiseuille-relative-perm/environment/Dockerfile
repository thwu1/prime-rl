FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip gmsh octave && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/pipeline
COPY config.py /app/config.py
COPY problem_description.txt /app/problem_description.txt
COPY pipeline/mesh.geo /app/pipeline/mesh.geo
COPY pipeline/solver.m /app/pipeline/solver.m
COPY pipeline/read_mesh.py /app/pipeline/read_mesh.py
COPY pipeline/postprocess.py /app/pipeline/postprocess.py
COPY pipeline/run_pipeline.sh /app/pipeline/run_pipeline.sh
RUN chmod +x /app/pipeline/run_pipeline.sh /app/pipeline/read_mesh.py /app/pipeline/postprocess.py

WORKDIR /app
