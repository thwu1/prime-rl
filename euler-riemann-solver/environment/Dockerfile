FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip make gnuplot-nox sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3 -q

WORKDIR /app
RUN mkdir -p /app/solver /app/results /app/convergence

COPY problems.json /app/problems.json
COPY run_solver.py /app/run_solver.py
COPY validate.py /app/validate.py
COPY Makefile /app/Makefile
COPY solver_init.py /app/solver/__init__.py
COPY exact_riemann.py /app/solver/exact_riemann.py
COPY fv_euler.py /app/solver/fv_euler.py
COPY convergence_init.py /app/convergence/__init__.py
COPY convergence_analyze.py /app/convergence/analyze.py
COPY convergence_config.json /app/convergence/config.json
COPY plot_convergence.gp /app/plot_convergence.gp
COPY import_results.sh /app/import_results.sh
