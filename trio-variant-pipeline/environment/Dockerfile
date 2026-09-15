FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    bcftools \
    tabix \
    wget \
    curl \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install slivar (bioinformatics trio/family variant filter)
RUN wget -q https://github.com/brentp/slivar/releases/download/v0.3.1/slivar -O /usr/local/bin/slivar && \
    chmod +x /usr/local/bin/slivar

# Install vcfanno (VCF annotation tool)
RUN wget -q https://github.com/brentp/vcfanno/releases/download/v0.3.5/vcfanno_linux64 -O /usr/local/bin/vcfanno && \
    chmod +x /usr/local/bin/vcfanno

# Set up genomic data files
COPY trio.vcf /tmp/trio.vcf
COPY popfreq.vcf /tmp/popfreq.vcf
COPY regions.bed /tmp/regions.bed
COPY setup_data.sh /tmp/setup_data.sh

RUN bash /tmp/setup_data.sh

# Install the analysis pipeline
COPY pipeline_run.sh /app/pipeline/run.sh
COPY pipeline_vcfanno.toml /app/pipeline/vcfanno.toml
COPY pipeline_ped.txt /app/pipeline/trio.ped
RUN chmod +x /app/pipeline/run.sh

RUN mkdir -p /app/results

WORKDIR /app
