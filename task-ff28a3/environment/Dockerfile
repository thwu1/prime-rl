FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip samtools bwa minimap2 tabix && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY reference.fa /app/data/reference.fa
COPY alignments.sam /app/data/alignments.sam
COPY targets.bed /app/data/targets.bed
COPY assembly.fa /app/data/assembly.fa
COPY notes.txt /app/data/notes.txt

WORKDIR /app
