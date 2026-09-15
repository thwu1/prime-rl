
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN git init && \
    git config user.email "dev@pbt-framework.internal" && \
    git config user.name "Framework Developer"

COPY choiceseq.py /app/choiceseq.py
COPY runner.py /app/runner.py
RUN git add -A && git commit -m "Add typed choice sequence model and test execution engine"

COPY shrinker.py /app/shrinker.py
RUN git add -A && git commit -m "Add shrinker skeleton with sequence evaluation protocol"

COPY validate.py /app/validate.py
RUN git add -A && git commit -m "Add development validation harness with test scenarios"
