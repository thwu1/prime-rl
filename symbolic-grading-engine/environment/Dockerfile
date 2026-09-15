FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/challenges /app/submissions

COPY grading_spec.md /app/GRADING_SPEC.md

COPY challenges/challenge_alpha.json /app/challenges/challenge_alpha.json
COPY challenges/challenge_beta.json /app/challenges/challenge_beta.json
COPY challenges/challenge_gamma.json /app/challenges/challenge_gamma.json
COPY challenges/challenge_delta.json /app/challenges/challenge_delta.json
COPY challenges/challenge_epsilon.json /app/challenges/challenge_epsilon.json
COPY challenges/challenge_zeta.json /app/challenges/challenge_zeta.json

COPY submissions/submission_alpha_correct.json /app/submissions/submission_alpha_correct.json
COPY submissions/submission_alpha_wrong.json /app/submissions/submission_alpha_wrong.json
COPY submissions/submission_beta_correct.json /app/submissions/submission_beta_correct.json
COPY submissions/submission_beta_wrong.json /app/submissions/submission_beta_wrong.json
COPY submissions/submission_gamma_correct.json /app/submissions/submission_gamma_correct.json
COPY submissions/submission_gamma_wrong.json /app/submissions/submission_gamma_wrong.json
COPY submissions/submission_delta_correct.json /app/submissions/submission_delta_correct.json
COPY submissions/submission_delta_wrong.json /app/submissions/submission_delta_wrong.json
COPY submissions/submission_epsilon_correct.json /app/submissions/submission_epsilon_correct.json
COPY submissions/submission_epsilon_wrong.json /app/submissions/submission_epsilon_wrong.json
COPY submissions/submission_zeta_correct.json /app/submissions/submission_zeta_correct.json
COPY submissions/submission_zeta_wrong.json /app/submissions/submission_zeta_wrong.json

WORKDIR /app
