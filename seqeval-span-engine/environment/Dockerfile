FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip perl && rm -rf /var/lib/apt/lists/*


COPY conlleval.pl /app/conlleval.pl
RUN chmod +x /app/conlleval.pl

COPY data/sample.conll /app/data/sample.conll
COPY data/sample.eval /app/data/sample.eval

COPY baseline.py /app/baseline.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 seqeval==1.2.2 numpy==1.26.4 scikit-learn==1.5.2
