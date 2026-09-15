FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/nicob /app/data /app/results

COPY nicob/modifiedKHmethod.R /app/nicob/modifiedKHmethod.R
COPY nicob/sampleFromTau2Dist.R /app/nicob/sampleFromTau2Dist.R
COPY nicob/linearOP.R /app/nicob/linearOP.R
COPY nicob/DoEUnilateralDerSimonianLaird.R /app/nicob/DoEUnilateralDerSimonianLaird.R
COPY nicob/symmetricalBootstrapCI.R /app/nicob/symmetricalBootstrapCI.R

COPY data/pcb28.ncb /app/data/pcb28.ncb
COPY data/gauge_blocks.ncb /app/data/gauge_blocks.ncb
COPY data/radionuclide.ncb /app/data/radionuclide.ncb

WORKDIR /app
