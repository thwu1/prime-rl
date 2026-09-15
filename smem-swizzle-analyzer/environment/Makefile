
BUILD_DIR := build
LIB_DIR := lib

.PHONY: all build run clean

all: run

build:
	cmake -S . -B $(BUILD_DIR) -DCMAKE_INSTALL_PREFIX=$(CURDIR)
	cmake --build $(BUILD_DIR) -j$$(nproc)
	cmake --install $(BUILD_DIR)
	@echo "Library built and installed successfully."

run: build
	python3 run_optimizer.py

clean:
	rm -rf $(BUILD_DIR) $(LIB_DIR)
	rm -f optimal_layouts.json analysis_report.csv
