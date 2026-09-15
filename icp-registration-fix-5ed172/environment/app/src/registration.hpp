#pragma once

#include <Eigen/Dense>

struct PointCloud;

struct RegistrationResult {
    Eigen::Matrix4f transformation;
    float fitness_score;
    int iterations;
    bool converged;
};

/// Align source cloud to target cloud using point-to-plane ICP.
/// Returns the transformation T such that T * source ≈ target.
RegistrationResult alignPointToPlane(
    const PointCloud& source,
    const PointCloud& target,
    int max_iterations = 50,
    float max_correspondence_dist = 0.15f,
    float convergence_epsilon = 1e-6f
);
