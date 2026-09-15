#!/bin/bash

pip3 install numpy==1.26.4 -q

# Implement the complete pipeline from scratch
python3 /solution/implement.py

# Verify by running the pipeline on all evaluation scenarios
echo "=== Running KITTI SE(3) evaluation ==="
python3 /app/slam_eval/pipeline.py \
    --format kitti \
    --gt /app/data/kitti_gt.txt \
    --est /app/data/kitti_est.txt \
    --output /app/results/kitti.json \
    --align se3

echo "=== Running TUM SE(3) evaluation ==="
python3 /app/slam_eval/pipeline.py \
    --format tum \
    --gt /app/data/tum_gt.txt \
    --est /app/data/tum_est.txt \
    --output /app/results/tum.json \
    --align se3

echo "=== Running EuRoC Sim(3) evaluation ==="
python3 /app/slam_eval/pipeline.py \
    --format euroc \
    --gt /app/data/euroc_gt.csv \
    --est /app/data/euroc_est.txt \
    --output /app/results/euroc_sim3.json \
    --align sim3 \
    --max_diff 0.03

echo "=== Running EuRoC SE(3) evaluation ==="
python3 /app/slam_eval/pipeline.py \
    --format euroc \
    --gt /app/data/euroc_gt.csv \
    --est /app/data/euroc_est.txt \
    --output /app/results/euroc_se3.json \
    --align se3 \
    --max_diff 0.03

echo "=== Running RANSAC on outlier data ==="
python3 /app/slam_eval/pipeline.py \
    --format tum \
    --gt /app/data/tum_gt.txt \
    --est /app/data/tum_outliers_est.txt \
    --output /app/results/tum_ransac.json \
    --align se3 \
    --robust \
    --ransac_seed 42

echo "=== Running RPE on KITTI ==="
python3 /app/slam_eval/pipeline.py \
    --format kitti \
    --gt /app/data/kitti_gt.txt \
    --est /app/data/kitti_est.txt \
    --output /app/results/kitti_rpe.json \
    --align se3 \
    --rpe

echo "=== All evaluations complete ==="
for f in /app/results/*.json; do
    echo "--- $(basename $f) ---"
    python3 -m json.tool "$f"
    echo
done
