FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-numpy \
    python3-scipy \
    python3-netcdf4 \
    cdo \
    nco \
    && rm -rf /var/lib/apt/lists/*

# Generate synthetic climate dataset
RUN mkdir -p /app/data
COPY generate_dataset.py /tmp/generate_dataset.py
RUN python3 /tmp/generate_dataset.py && rm /tmp/generate_dataset.py

# Dataset documentation
COPY data_readme.txt /app/data/README.txt

# Set up the flawed analysis pipeline
RUN mkdir -p /app/pipeline
COPY run_analysis.sh /app/pipeline/run_analysis.sh
COPY eof_analysis.py /app/pipeline/eof_analysis.py
COPY gregory.py /app/pipeline/gregory.py
COPY combine_results.py /app/pipeline/combine_results.py
RUN chmod +x /app/pipeline/run_analysis.sh

# Run the flawed pipeline to produce original results
RUN /app/pipeline/run_analysis.sh

WORKDIR /app
