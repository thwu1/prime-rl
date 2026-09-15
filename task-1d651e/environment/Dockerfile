
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip glpk-utils && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/pipeline /app/data/instances /app/data/scenarios \
             /app/tools /app/logs /app/output

COPY pipeline/solver.py /app/pipeline/solver.py
COPY pipeline/config.ini /app/pipeline/config.ini
COPY pipeline/run_pipeline.sh /app/pipeline/run_pipeline.sh
RUN chmod +x /app/pipeline/run_pipeline.sh

COPY data/instances/prob_alpha.dat /app/data/instances/prob_alpha.dat
COPY data/instances/prob_beta.dat /app/data/instances/prob_beta.dat
COPY data/instances/prob_gamma.dat /app/data/instances/prob_gamma.dat

COPY data/scenarios/scenario_alpha.json /app/data/scenarios/scenario_alpha.json
COPY data/scenarios/scenario_beta.json /app/data/scenarios/scenario_beta.json
COPY data/scenarios/scenario_gamma.json /app/data/scenarios/scenario_gamma.json

COPY tools/relax_template.mod /app/tools/relax_template.mod
COPY tools/validate.py /app/tools/validate.py

COPY logs/run_2024_03_15.log /app/logs/run_2024_03_15.log
COPY logs/run_2024_03_18.log /app/logs/run_2024_03_18.log

WORKDIR /app
