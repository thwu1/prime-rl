FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/output /app/kasan_reports /app/docs

COPY init_structs.sql /tmp/init_structs.sql
RUN sqlite3 /app/kernel_structs.db < /tmp/init_structs.sql && rm /tmp/init_structs.sql

COPY slabinfo /app/slabinfo
COPY mitigations.json /app/mitigations.json
COPY output_spec.json /app/output_spec.json
COPY slub_allocator.txt /app/docs/slub_allocator.txt

COPY vuln_1.txt /app/kasan_reports/vuln_1.txt
COPY vuln_2.txt /app/kasan_reports/vuln_2.txt
COPY vuln_3.txt /app/kasan_reports/vuln_3.txt

COPY setup_sysfs.sh /tmp/setup_sysfs.sh
RUN chmod +x /tmp/setup_sysfs.sh && /tmp/setup_sysfs.sh && rm /tmp/setup_sysfs.sh

WORKDIR /app
