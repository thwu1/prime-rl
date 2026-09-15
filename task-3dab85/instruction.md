A retrieval evaluation job is specified in `/app/job.json`. It references system output files in `/app/runs/` and relevance judgments in `/app/qrels.txt`.

Some of the run files contain data quality problems that will silently corrupt evaluation results if not identified and corrected first. Produce all outputs described in the job specification to `/app/output/`.