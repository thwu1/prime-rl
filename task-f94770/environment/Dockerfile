FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN pip3 install mujoco==3.2.6 qpsolvers==4.3.3 daqp==0.8.7

WORKDIR /app
COPY robot.xml /app/robot.xml
COPY ik_solver.py /app/ik_solver.py
