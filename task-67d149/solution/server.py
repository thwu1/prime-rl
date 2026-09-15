"""

gRPC test prioritization server. Implements the CompetitionTool service.
Extracts curvature-informed road geometry features from oracle data,
trains a logistic regression classifier, and prioritizes unlabeled
tests by predicted failure probability.

Feature engineering rationale: curvature profile theory (SPEC.md §2)
shows that road difficulty is characterized by the distribution of
curvature along the road. Rather than using full curvature profiles
(which overfit on small training sets due to high dimensionality),
we compute 7 aggregate curvature statistics that capture the same
geometric difficulty signal with lower variance.
"""
import math
import sys

sys.path.insert(0, "/app")

import grpc
from concurrent import futures

import interface_pb2
import interface_pb2_grpc


def _extract_features(road_points):
    """Extract curvature-informed geometry features from road point sequence.

    Features (7 dimensions):
    - Total curvature: sum of absolute angular changes
    - Max curvature: largest single angular change
    - Mean curvature: average angular change
    - Curvature std: standard deviation of angular changes
    - Total road length: sum of segment arc lengths
    - Sinuosity: total length / direct endpoint distance
    - Sharp turn count: segments with angular change > 0.3 rad
    """
    xs = [pt.x for pt in road_points]
    ys = [pt.y for pt in road_points]
    n = len(xs)
    if n < 3:
        return [0.0] * 7

    # Segment arc lengths
    seg_lengths = [
        math.sqrt((xs[i + 1] - xs[i]) ** 2 + (ys[i + 1] - ys[i]) ** 2)
        for i in range(n - 1)
    ]
    total_length = sum(seg_lengths)

    # Angular changes between consecutive segments (discrete curvature proxy)
    angles = []
    for i in range(n - 2):
        theta_i = math.atan2(ys[i + 1] - ys[i], xs[i + 1] - xs[i])
        theta_next = math.atan2(ys[i + 2] - ys[i + 1], xs[i + 2] - xs[i + 1])
        diff = abs(theta_next - theta_i)
        if diff > math.pi:
            diff = 2 * math.pi - diff
        angles.append(diff)

    total_curv = sum(angles)
    max_curv = max(angles) if angles else 0.0
    mean_curv = total_curv / len(angles) if angles else 0.0
    std_curv = (
        math.sqrt(sum((a - mean_curv) ** 2 for a in angles) / len(angles))
        if len(angles) > 1
        else 0.0
    )

    # Sinuosity: ratio of road length to direct distance
    direct = math.sqrt((xs[-1] - xs[0]) ** 2 + (ys[-1] - ys[0]) ** 2)
    sinuosity = total_length / direct if direct > 1e-9 else 1.0

    # Count sharp turns (angular change > ~17 degrees)
    sharp = float(sum(1 for a in angles if a > 0.3))

    return [total_curv, max_curv, mean_curv, std_curv, total_length, sinuosity, sharp]


def _sigmoid(x):
    x = max(-500.0, min(500.0, x))
    return 1.0 / (1.0 + math.exp(-x))


class Prioritizer(interface_pb2_grpc.CompetitionToolServicer):
    def __init__(self):
        self.weights = None
        self.bias = 0.0
        self.means = None
        self.stds = None

    def Name(self, request, context):
        return interface_pb2.NameReply(name="curvature_aware_prioritizer")

    def Initialize(self, request_iterator, context):
        features_list = []
        labels = []
        for oracle in request_iterator:
            feats = _extract_features(oracle.testCase.roadPoints)
            features_list.append(feats)
            labels.append(1.0 if oracle.hasFailed else 0.0)

        if features_list and sum(labels) > 0:
            self._train(features_list, labels)

        return interface_pb2.InitializationReply(ok=True)

    def Prioritize(self, request_iterator, context):
        cases = []
        feats_list = []
        for tc in request_iterator:
            cases.append(tc)
            feats_list.append(_extract_features(tc.roadPoints))

        if self.weights and self.means and self.stds:
            probs = []
            for feats in feats_list:
                normalized = [
                    (feats[j] - self.means[j]) / self.stds[j]
                    for j in range(len(self.means))
                ]
                z = (
                    sum(
                        self.weights[j] * normalized[j]
                        for j in range(len(self.weights))
                    )
                    + self.bias
                )
                probs.append(_sigmoid(z))
        else:
            # Fallback: use total curvature as heuristic score
            probs = [f[0] for f in feats_list]

        indices = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
        for idx in indices:
            yield interface_pb2.PrioritizationReply(testId=cases[idx].testId)

    def _train(self, X, y):
        """Train logistic regression via mini-batch SGD with feature normalization."""
        n_feat = len(X[0])

        # Compute feature statistics for z-score normalization
        means = [sum(x[j] for x in X) / len(X) for j in range(n_feat)]
        stds = [
            max(
                1e-9,
                math.sqrt(sum((x[j] - means[j]) ** 2 for x in X) / len(X)),
            )
            for j in range(n_feat)
        ]

        X_norm = [
            [(x[j] - means[j]) / stds[j] for j in range(n_feat)] for x in X
        ]

        # SGD with learning rate schedule
        w = [0.0] * n_feat
        b = 0.0
        lr = 0.01
        for epoch in range(1000):
            if epoch == 500:
                lr = 0.005
            for i in range(len(X_norm)):
                z = sum(w[j] * X_norm[i][j] for j in range(n_feat)) + b
                pred = _sigmoid(z)
                err = pred - y[i]
                for j in range(n_feat):
                    w[j] -= lr * err * X_norm[i][j]
                b -= lr * err

        self.weights = w
        self.bias = b
        self.means = means
        self.stds = stds


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    interface_pb2_grpc.add_CompetitionToolServicer_to_server(Prioritizer(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    print("gRPC server listening on port 50051", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
