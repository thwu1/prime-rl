
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gnuplot-nox sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/submissions /app/experimental /app/results/plots

COPY submissions/ /app/submissions/
COPY experimental/ /app/experimental/
COPY format_spec.txt /app/format_spec.txt

WORKDIR /app
