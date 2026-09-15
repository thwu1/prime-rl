
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip r-base && rm -rf /var/lib/apt/lists/*

RUN Rscript -e 'install.packages("metafor", repos="https://cloud.r-project.org/")'

RUN mkdir -p /app/data /app/nicob_r

COPY data/pcb28.ncb /app/data/pcb28.ncb
COPY data/gauge.ncb /app/data/gauge.ncb
COPY data/radionuclide.ncb /app/data/radionuclide.ncb

COPY nicob_r/modifiedKHmethod.R /app/nicob_r/modifiedKHmethod.R
COPY nicob_r/sampleFromTau2Dist.R /app/nicob_r/sampleFromTau2Dist.R
COPY nicob_r/linearOP.R /app/nicob_r/linearOP.R
COPY nicob_r/symmetricalBootstrapCI.R /app/nicob_r/symmetricalBootstrapCI.R
COPY nicob_r/DoEUnilateralDerSimonianLaird.R /app/nicob_r/DoEUnilateralDerSimonianLaird.R
COPY nicob_r/DoEBilateralDerSimonianLaird.R /app/nicob_r/DoEBilateralDerSimonianLaird.R

WORKDIR /app
