FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PYTHONPATH=/app


RUN apt-get update && apt-get install -y python3 python3-pip git sqlite3 && rm -rf /var/lib/apt/lists/*

COPY app/ /app/
COPY reference/ /app/reference/

WORKDIR /app

RUN git config --global user.email "dev@example.com" && \
    git config --global user.name "Developer" && \
    git config --global init.defaultBranch main && \
    git config --global --add safe.directory /app && \
    git init && \
    git add -A && \
    git commit -m "Initial: skeleton with reference material" && \
    rm -rf /app/reference && \
    git add -A && \
    git commit -m "Remove reference files"
