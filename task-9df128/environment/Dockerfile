FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 libxml2-utils && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY nav2_params.yaml /app/nav2_params.yaml
COPY robot_spec.yaml /app/robot_spec.yaml
COPY validate_config.py /app/validate_config.py
COPY migration_notes.md /app/migration_notes.md
COPY nav2_bt.xml /app/nav2_bt.xml
COPY init_fleet_db.sql /tmp/init_fleet_db.sql

RUN sqlite3 /app/fleet.db < /tmp/init_fleet_db.sql && rm /tmp/init_fleet_db.sql

RUN chmod +x /app/validate_config.py

RUN pip3 install pyyaml==6.0.2 -q

WORKDIR /app
