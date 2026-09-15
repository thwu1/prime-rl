FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip bedtools && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/results

COPY data/motifs.meme /app/data/motifs.meme
COPY data/promoters_train.fa /app/data/promoters_train.fa
COPY data/promoters_test.fa /app/data/promoters_test.fa
COPY data/accessibility.bed /app/data/accessibility.bed
COPY data/expression_train.tsv /app/data/expression_train.tsv
COPY data/chipseq_TFC.narrowPeak /app/data/chipseq_TFC.narrowPeak
COPY data/genome.sizes /app/data/genome.sizes
COPY data/README.txt /app/data/README.txt

WORKDIR /app
