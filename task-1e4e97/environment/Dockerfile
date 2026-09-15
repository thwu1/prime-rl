
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip python3-dev git && rm -rf /var/lib/apt/lists/*
RUN pip3 install numpy==2.1.3 scipy==1.14.1

COPY frame3d/ /app/frame3d/
WORKDIR /app

RUN printf '__pycache__/\n*.pyc\n*.pyo\n' > .gitignore && \
    git config --global user.email "dev@frame3d.org" && \
    git config --global user.name "frame3d" && \
    git init && \
    git add -A && \
    git commit -m "Initial commit: frame3d package with elastic solver and buckling stubs" && \
    git rm frame3d/config.py && \
    git commit -m "Remove unused config module"
