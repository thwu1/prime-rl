FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==1.26.4 -q

RUN mkdir -p /app/data/experiment_1 /app/data/experiment_2 /app/data/holdout /app/src /app/logs /app/output

COPY project_readme.md /app/README.md
COPY config.yaml /app/config.yaml
COPY hmm_model_buggy.py /app/src/hmm_model.py
COPY run_mcmc_buggy.py /app/src/run_mcmc.py
COPY mcmc_K3.log /app/logs/mcmc_K3.log
COPY mcmc_K2.log /app/logs/mcmc_K2.log

COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py && rm /tmp/generate_data.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 numpy==1.26.4
