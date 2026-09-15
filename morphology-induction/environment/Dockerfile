FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 jq xmlstarlet && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/results

COPY data/genome_sequences.fasta /app/data/genome_sequences.fasta
RUN gzip /app/data/genome_sequences.fasta

COPY data/init_db.sql /tmp/init_db.sql
RUN sqlite3 /app/data/proteomics.db < /tmp/init_db.sql && rm /tmp/init_db.sql

COPY data/experiment_metadata.xml /app/data/experiment_metadata.xml

COPY data/batch_reports/ /tmp/batch_reports/
RUN cd /tmp && tar czf /app/data/batch_reports.tar.gz batch_reports/ && rm -rf /tmp/batch_reports

WORKDIR /app
