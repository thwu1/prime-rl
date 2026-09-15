FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-numpy \
    python3-yaml \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/data/scenario1 /app/data/scenario2 /app/data/scenario3 \
    /app/data/scenario4 /app/data/scenario5 \
    /app/expected /app/recbole_src /app/results

COPY eval_tool.py /app/eval_tool.py
COPY score_converter.py /app/score_converter.py

COPY recbole_src/metrics.py /app/recbole_src/metrics.py
COPY recbole_src/collector.py /app/recbole_src/collector.py

COPY data/scenario1/ranked_lists.json /app/data/scenario1/ranked_lists.json
COPY data/scenario1/ground_truth.json /app/data/scenario1/ground_truth.json
COPY data/scenario1/config.json /app/data/scenario1/config.json

COPY data/scenario2/ranked_lists.json /app/data/scenario2/ranked_lists.json
COPY data/scenario2/ground_truth.json /app/data/scenario2/ground_truth.json
COPY data/scenario2/config.json /app/data/scenario2/config.json

COPY data/scenario3/ranked_lists.json /app/data/scenario3/ranked_lists.json
COPY data/scenario3/ground_truth.json /app/data/scenario3/ground_truth.json
COPY data/scenario3/config.json /app/data/scenario3/config.json

COPY data/scenario4/scores.json /app/data/scenario4/scores.json
COPY data/scenario4/relevance.json /app/data/scenario4/relevance.json
COPY data/scenario4/eval_config.yaml /app/data/scenario4/eval_config.yaml

COPY data/scenario5/scores.json /app/data/scenario5/scores.json
COPY data/scenario5/relevance.json /app/data/scenario5/relevance.json
COPY data/scenario5/eval_config.yaml /app/data/scenario5/eval_config.yaml

COPY expected/scenario1.json /app/expected/scenario1.json
COPY expected/scenario2.json /app/expected/scenario2.json
COPY expected/scenario3.json /app/expected/scenario3.json

WORKDIR /app
