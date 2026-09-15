
#include "registration.hpp"
#include "point_cloud.hpp"
#include <iostream>
#include <cmath>
#include <limits>
#include <algorithm>
#include <vector>

// ---------------------------------------------------------------------------
// Estimate surface normals via PCA on K nearest neighbours.
// For each point, find K closest points and fit a plane using eigenanalysis
// of the neighbourhood covariance matrix.
// ---------------------------------------------------------------------------
static std::vector<Eigen::Vector3f> estimateNormals(
    const PointCloud& cloud, int k)
{
    std::vector<Eigen::Vector3f> normals(cloud.size());

    for (std::size_t i = 0; i < cloud.size(); ++i) {
        // Brute-force K-nearest-neighbour search
        std::vector<std::pair<float, std::size_t>> dists;
        dists.reserve(cloud.size());
        for (std::size_t j = 0; j < cloud.size(); ++j) {
            if (i == j) continue;
            float d2 = (cloud.points[i] - cloud.points[j]).squaredNorm();
            dists.push_back({d2, j});
        }
        int nk = std::min(k, static_cast<int>(dists.size()));
        std::partial_sort(dists.begin(), dists.begin() + nk, dists.end());

        // Build covariance matrix from neighbourhood for PCA
        Eigen::Matrix3f cov = Eigen::Matrix3f::Zero();
        for (int ni = 0; ni < nk; ++ni) {
            const Eigen::Vector3f& p = cloud.points[dists[ni].second];
            cov += p * p.transpose();
        }
        cov /= static_cast<float>(nk);

        // Smallest eigenvector of covariance = surface normal direction
        Eigen::SelfAdjointEigenSolver<Eigen::Matrix3f> solver(cov);
        normals[i] = solver.eigenvectors().col(0);
        normals[i].normalize();
    }

    return normals;
}

// ---------------------------------------------------------------------------
// Find the nearest neighbour of `query` in `target` (brute force).
// Returns (index, squared_distance).
// ---------------------------------------------------------------------------
static std::pair<int, float> findNearestNeighbor(
    const Eigen::Vector3f& query, const PointCloud& target)
{
    float best_d2 = std::numeric_limits<float>::max();
    int best_idx = -1;

    for (std::size_t i = 0; i < target.size(); ++i) {
        float d2 = (query - target.points[i]).squaredNorm();
        if (d2 < best_d2) {
            best_d2 = d2;
            best_idx = static_cast<int>(i);
        }
    }
    return {best_idx, best_d2};
}

// ---------------------------------------------------------------------------
// Solve one linearised point-to-plane ICP step.
// Builds and solves the 6x6 normal equations for the incremental
// transformation (alpha, beta, gamma, tx, ty, tz).
// ---------------------------------------------------------------------------
static Eigen::Matrix4f computePointToPlaneStep(
    const PointCloud& source,
    const PointCloud& target,
    const std::vector<Eigen::Vector3f>& source_normals,
    const std::vector<Eigen::Vector3f>& target_normals,
    float max_corr_dist,
    float &out_fitness)
{
    Eigen::Matrix<float, 6, 6> ATA = Eigen::Matrix<float, 6, 6>::Zero();
    Eigen::Matrix<float, 6, 1> ATb = Eigen::Matrix<float, 6, 1>::Zero();
    int n_corr = 0;
    float err_sum = 0.0f;

    for (std::size_t i = 0; i < source.size(); ++i) {
        auto [nn_idx, nn_dist2] = findNearestNeighbor(source.points[i], target);
        if (nn_idx < 0) continue;

        // Reject correspondences whose distance exceeds the threshold
        if (nn_dist2 > max_corr_dist)
            continue;

        // Obtain the surface normal for the point-to-plane residual
        const Eigen::Vector3f& n = source_normals[i];
        if (n.squaredNorm() < 0.5f) continue;

        Eigen::Vector3f nrm = n.normalized();
        Eigen::Vector3f s = source.points[i];
        Eigen::Vector3f t = target.points[nn_idx];

        // Linearised point-to-plane: minimise sum_i ((R*s_i + t - t_i) . n_i)^2
        // With small-angle approximation R ~ I + [alpha,beta,gamma]x this is
        // linear in the 6 unknowns.
        Eigen::Vector3f cross = s.cross(nrm);
        Eigen::Matrix<float, 6, 1> row;
        row << cross(0), cross(1), cross(2), nrm(0), nrm(1), nrm(2);

        float rhs = (t - s).dot(nrm);

        ATA += row * row.transpose();
        ATb += row * rhs;

        err_sum += (t - s).squaredNorm();
        n_corr++;
    }

    out_fitness = (n_corr > 0)
        ? err_sum / static_cast<float>(n_corr)
        : std::numeric_limits<float>::max();

    if (n_corr < 10) {
        std::cerr << "[ICP] Warning: only " << n_corr
                  << " valid correspondences at this step" << std::endl;
        return Eigen::Matrix4f::Identity();
    }

    // Solve the 6x6 system
    Eigen::Matrix<float, 6, 1> x = ATA.ldlt().solve(ATb);
    float a = x(0), b = x(1), g = x(2);
    float tx = x(3), ty = x(4), tz = x(5);

    // Build the incremental transformation from small-angle rotation + translation
    Eigen::Matrix4f delta = Eigen::Matrix4f::Identity();
    delta(0, 1) = -g;  delta(0, 2) =  b;  delta(0, 3) = tx;
    delta(1, 0) =  g;  delta(1, 2) = -a;  delta(1, 3) = ty;
    delta(2, 0) = -b;  delta(2, 1) =  a;  delta(2, 3) = tz;

    return delta;
}

// ---------------------------------------------------------------------------
// Iterative point-to-plane alignment
// ---------------------------------------------------------------------------
RegistrationResult alignPointToPlane(
    const PointCloud& source,
    const PointCloud& target,
    int max_iterations,
    float max_correspondence_dist,
    float convergence_epsilon)
{
    RegistrationResult result;
    result.transformation = Eigen::Matrix4f::Identity();
    result.converged = false;
    result.iterations = 0;

    // Estimate surface normals for both clouds once up front
    auto src_normals = estimateNormals(source, 20);
    auto tgt_normals = estimateNormals(target, 20);

    // Working copy of the source cloud; iteratively transformed toward target
    PointCloud working;
    working.points = source.points;

    // Keep a copy of the source normals that travels with the working cloud
    std::vector<Eigen::Vector3f> wrk_normals = src_normals;

    Eigen::Matrix4f accumulated = Eigen::Matrix4f::Identity();

    for (int iter = 0; iter < max_iterations; ++iter) {
        float fitness;
        Eigen::Matrix4f delta = computePointToPlaneStep(
            working, target, wrk_normals, tgt_normals,
            max_correspondence_dist, fitness);

        // Apply the incremental transform to the working cloud
        for (auto& p : working.points) {
            Eigen::Vector4f hp(p.x(), p.y(), p.z(), 1.0f);
            hp = delta * hp;
            p = hp.head<3>();
        }

        // Accumulate the total source-to-target transformation
        accumulated = accumulated * delta;

        result.fitness_score = fitness;
        result.iterations = iter + 1;

        // Check convergence: is the incremental change negligible?
        float change = delta.norm();
        if (change < convergence_epsilon) {
            result.converged = true;
            break;
        }
    }

    result.transformation = accumulated;
    return result;
}
