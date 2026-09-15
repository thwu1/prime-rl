# Warehouse navigation pipeline orchestration
# Usage: make all

.PHONY: all clean

DB_PATH := /app/pipeline.db
PYTHON  := python3

all: validate

pipeline:
	rm -f $(DB_PATH)
	cd /app && $(PYTHON) src/pipeline.py --db $DB_PATH

validate: pipeline
	jq -e '(.robot_geometry | has("inscribed_radius", "circumscribed_radius", "footprint_vertices")) and (.costmap_analysis | has("lethal_cell_count", "inflated_cell_count", "max_cost", "inflation_coverage_ratio")) and (.transform_chain | has("map_to_odom", "odom_to_base", "composed", "test_point_input", "test_point_output")) and (.route_plan | has("waypoint_order", "total_cost")) and (.route_plan.segments | length > 0)' /app/results.json > /dev/null
	@echo "Schema validation passed"

clean:
	rm -f $(DB_PATH) /app/results.json
