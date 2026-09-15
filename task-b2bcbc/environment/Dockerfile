FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip git && rm -rf /var/lib/apt/lists/*

RUN pip3 install mutmut==3.5.0

ENV PYTHONPATH=/app

RUN mkdir -p /app/intervallib /app/tests

COPY app/intervallib/__init__.py /app/intervallib/__init__.py
COPY app/intervallib/intervals.py /app/intervallib/intervals.py
COPY app/intervallib/scheduling.py /app/intervallib/scheduling.py
COPY app/intervallib/solver.py /app/intervallib/solver.py
COPY app/tests/test_intervals.py /app/tests/test_intervals.py
COPY app/tests/test_scheduling.py /app/tests/test_scheduling.py
COPY app/tests/test_solver.py /app/tests/test_solver.py
COPY app/mutations.json /app/mutations.json
COPY app/pyproject.toml /app/pyproject.toml

RUN python3 -c "import sys; sys.path.insert(0, '/app'); from intervallib import solver; print('solver.py loaded OK')"
RUN mutmut --version

WORKDIR /app

RUN git init && git config user.email "test@test.com" && git config user.name "Test" && git add -A && git commit -m "initial commit"

