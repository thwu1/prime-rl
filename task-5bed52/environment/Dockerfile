FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip make graphviz jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/programs /app/results

COPY prog1.tac /app/programs/prog1.tac
COPY prog2.tac /app/programs/prog2.tac
COPY prog3.tac /app/programs/prog3.tac

WORKDIR /app
