
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip ripgrep curl gawk && \
    rm -rf /var/lib/apt/lists/*

# Install xsv (BurntSushi's CSV toolkit)
RUN curl -fsSL https://github.com/BurntSushi/xsv/releases/download/0.13.0/xsv-0.13.0-x86_64-unknown-linux-musl.tar.gz | \
    tar xz -C /usr/local/bin/

RUN mkdir -p /app/logs /app/output /app/strategies

COPY access.log /app/logs/access.log
COPY exceptions.log /app/logs/exceptions.log
COPY .app_errors.log /app/logs/.app_errors.log
COPY app_events.log /app/logs/app_events.log

COPY create_binary_log.py /tmp/create_binary_log.py
RUN python3 /tmp/create_binary_log.py && rm /tmp/create_binary_log.py

COPY reference.csv /app/reference.csv
COPY aggregate.py /app/aggregate.py

COPY aho_corasick.py /app/aho_corasick.py
COPY cli.py /app/cli.py
COPY pipeline.sh /app/pipeline.sh

COPY strategy_a.sh /app/strategies/strategy_a.sh
COPY strategy_b.sh /app/strategies/strategy_b.sh
COPY strategy_c.sh /app/strategies/strategy_c.sh
COPY run_strategy.sh /app/run_strategy.sh
RUN chmod +x /app/strategies/*.sh /app/run_strategy.sh /app/pipeline.sh

WORKDIR /app
