.PHONY: batch db-create db-stats

batch:
	mkdir -p /app/output
	/app/hgvs-tool batch /app/data/test_batch.tsv > /app/output/batch_results.json

db-create:
	mkdir -p /app/output
	/app/hgvs-tool db load /app/data/sample_variants.txt --db /app/output/variants.db

db-stats:
	/app/hgvs-tool db query --db /app/output/variants.db --sql "SELECT type, COUNT(*) as count FROM variants GROUP BY type ORDER BY type" > /app/output/db_stats.json
