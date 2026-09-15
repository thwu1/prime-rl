FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install regex==2024.11.6

COPY setup_tokenizer.py /tmp/setup_tokenizer.py
COPY training_corpus.txt /tmp/training_corpus.txt
RUN python3 /tmp/setup_tokenizer.py && rm -f /tmp/setup_tokenizer.py /tmp/training_corpus.txt
