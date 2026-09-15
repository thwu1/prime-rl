FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/tools /tmp/build_levels

COPY levels/level_1.txt /tmp/build_levels/level_1.txt
COPY levels/level_2.txt /tmp/build_levels/level_2.txt
COPY levels/level_3.txt /tmp/build_levels/level_3.txt
COPY levels/level_4.txt /tmp/build_levels/level_4.txt

COPY setup_db.py /tmp/setup_db.py
COPY config.json /app/config.json
COPY tools/validate_runner.py /app/tools/validate_runner.py
COPY tools/validate.sh /app/tools/validate.sh

RUN chmod +x /app/tools/validate.sh
RUN python3 /tmp/setup_db.py /tmp/build_levels
RUN rm -rf /tmp/setup_db.py /tmp/build_levels

WORKDIR /app
