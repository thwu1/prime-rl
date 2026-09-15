#!/bin/bash
set -e
cd /app

git init
git config user.email "dev@eval-pipeline.io"
git config user.name "Pipeline Developer"

# Commit 1: Project setup with evaluation specification
git add pipeline/__init__.py spec.md
git commit -m "Initial project setup with evaluation spec"

# Commit 2: Configuration system with TOML + YAML + env overrides
git add pipeline/config.py config/main.toml config/overrides.yaml
git commit -m "Implement config system with TOML base and YAML overrides"

# Commit 3: Preprocessing module for range and quality filtering
git add pipeline/preprocessing.py
git commit -m "Add range filtering and GT quality filtering"

# Commit 4: Greedy assignment module
git add pipeline/assignment.py
git commit -m "Implement greedy assignment with score-ordered matching"

# Commit 5: Metrics computation (AP, TP errors, CDS)
git add pipeline/metrics.py
git commit -m "Add AP computation, TP error metrics, and CDS"

# Commit 6: Main evaluator entry point and data files
git add run_eval.py data/
git commit -m "Add main evaluation entry point with Feather data"

# Commit 7: Makefile for pipeline orchestration
git add Makefile
git commit -m "Add Makefile for pipeline orchestration"
