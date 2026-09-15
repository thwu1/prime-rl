FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    samtools \
    bcftools \
    bedtools \
    tabix \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/pipeline /app/expected /app/output /app/tmp

COPY data/reference.fa /app/data/reference.fa
COPY data/genes.gff3 /app/data/genes.gff3
COPY data/variants.vcf /tmp/variants.vcf

RUN samtools faidx /app/data/reference.fa && \
    bgzip -c /tmp/variants.vcf > /app/data/variants.vcf.gz && \
    tabix -p vcf /app/data/variants.vcf.gz && \
    rm /tmp/variants.vcf

COPY pipeline/run_pipeline.sh /app/pipeline/run_pipeline.sh
COPY pipeline/classify_effects.py /app/pipeline/classify_effects.py
RUN chmod +x /app/pipeline/run_pipeline.sh

COPY expected/validation_subset.tsv /app/expected/validation_subset.tsv

WORKDIR /app
