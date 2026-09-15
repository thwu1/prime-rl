FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*


RUN mkdir -p /app/output /app/reg_tables

COPY portfolio_data.json /app/portfolio.json
COPY reg_tables/equity_risk_weights.tsv /app/reg_tables/equity_risk_weights.tsv
COPY reg_tables/equity_intra_corr.tsv /app/reg_tables/equity_intra_corr.tsv
COPY reg_tables/equity_cross_corr.tsv /app/reg_tables/equity_cross_corr.tsv
COPY reg_tables/fx_params.tsv /app/reg_tables/fx_params.tsv
COPY reg_tables/girr_risk_weights.tsv /app/reg_tables/girr_risk_weights.tsv
COPY reg_tables/girr_correlation.tsv /app/reg_tables/girr_correlation.tsv
COPY reg_tables/csr_nonsec_risk_weights.tsv /app/reg_tables/csr_nonsec_risk_weights.tsv
COPY reg_tables/csr_nonsec_intra_corr.tsv /app/reg_tables/csr_nonsec_intra_corr.tsv
COPY reg_tables/csr_nonsec_cross_corr.tsv /app/reg_tables/csr_nonsec_cross_corr.tsv
COPY reg_tables/drc_equity_risk_weights.tsv /app/reg_tables/drc_equity_risk_weights.tsv
COPY reg_tables/mar21_mar22_excerpt.txt /app/reg_tables/mar21_mar22_excerpt.txt

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
