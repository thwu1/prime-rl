FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*

COPY election_system.py /app/election_system.py
COPY patches/ /app/patches/
COPY setup_election.py /tmp/setup_election.py
RUN cd /app && python3 /tmp/setup_election.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip openssl sqlite3 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/election_system.py /app/election_system.py
COPY --from=builder /app/election.db /app/election.db
COPY --from=builder /app/audit.log /app/audit.log
COPY --from=builder /app/keys/ /app/keys/
COPY --from=builder /app/patches/ /app/patches/
