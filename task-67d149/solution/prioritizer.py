"""
Curvature-aware test prioritizer gRPC server.

Extracts road geometry features from oracle test cases, trains a classifier,
and uses predicted failure probabilities to prioritize test cases.
"""
import math
import sys
import os

sys.path.insert(0, "/app")

import interface_pb2
import interface_pb2_grpc


def extract_road_features(road_points):
    """Extract curvature and geometry features from road points."""
    xs = [pt.x for pt in road_points]
    ys = [pt.y for pt in road_points]
    return _compute_features(xs, ys)


def _compute_features(xs, ys):
    """Core feature computation from coordinate lists."""
    n = len(xs)
    if n < 3:
        return [0.0] * 7

    # Segment lengths
    seg_lengths = []
    for i in range(n - 1):
        dx = xs[i + 1] - xs[i]
        dy = ys[i + 1] - ys[i]
        seg_lengths.append(math.sqrt(dx * dx + dy * dy))

    total_length = sum(seg_lengths)

    # Angles between consecutive segments
    angles = []
    for i in range(n - 2):
        dx1 = xs[i + 1] - xs[i]
        dy1 = ys[i + 1] - ys[i]
        dx2 = xs[i + 2] - xs[i + 1]
        dy2 = ys[i + 2] - ys[i + 1]
        a1 = math.atan2(dy1, dx1)
        a2 = math.atan2(dy2, dx2)
        diff = abs(a2 - a1)
        if diff > math.pi:
            diff = 2 * math.pi - diff
        angles.append(diff)

    total_curvature = sum(angles)
    max_curvature = max(angles) if angles else 0.0
    mean_curvature = total_curvature / len(angles) if angles else 0.0

    # Standard deviation of curvature
    if len(angles) > 1:
        var = sum((a - mean_curvature) ** 2 for a in angles) / len(angles)
        std_curvature = math.sqrt(var)
    else:
        std_curvature = 0.0

    # Direct distance (start to end)
    direct_dist = math.sqrt((xs[-1] - xs[0]) ** 2 + (ys[-1] - ys[0]) ** 2)

    # Sinuosity: ratio of total road length to direct distance
    sinuosity = total_length / direct_dist if direct_dist > 1e-9 else 1.0

    # Count sharp turns (angle > 0.3 radians ~17 degrees)
    sharp_turns = sum(1 for a in angles if a > 0.3)

    return [
        total_curvature,
        max_curvature,
        mean_curvature,
        std_curvature,
        total_length,
        sinuosity,
        float(sharp_turns),
    ]


class CurvaturePrioritizer(interface_pb2_grpc.CompetitionToolServicer):
    def __init__(self):
        self.oracle_features = []
        self.oracle_labels = []
        self.model = None
        self.scaler = None

    def Name(self, request, context):
        return interface_pb2.NameReply(name="curvature_prioritizer")

    def Initialize(self, request_iterator, context):
        """Receive oracle data and train a failure prediction model."""
        for oracle in request_iterator:
            features = extract_road_features(oracle.testCase.roadPoints)
            self.oracle_features.append(features)
            self.oracle_labels.append(1 if oracle.hasFailed else 0)

        # Train a logistic regression with feature scaling
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        if len(self.oracle_features) > 0 and sum(self.oracle_labels) > 0:
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(self.oracle_features)
            self.model = LogisticRegression(random_state=42, C=0.1, max_iter=1000)
            self.model.fit(X_scaled, self.oracle_labels)

        return interface_pb2.InitializationReply(ok=True)

    def Prioritize(self, request_iterator, context):
        """Receive test cases and return them prioritized by predicted failure probability."""
        test_cases = []
        test_features = []

        for sdc_test_case in request_iterator:
            test_cases.append(sdc_test_case)
            features = extract_road_features(sdc_test_case.roadPoints)
            test_features.append(features)

        if self.model is not None and self.scaler is not None and len(test_features) > 0:
            # Use ML model to predict failure probability
            X_scaled = self.scaler.transform(test_features)
            probs = self.model.predict_proba(X_scaled)
            fail_probs = [p[1] if len(p) > 1 else 0.0 for p in probs]
        else:
            # Fallback: use total curvature as score
            fail_probs = [f[0] for f in test_features]

        # Sort by failure probability descending (higher = more likely to fail = prioritize first)
        indexed = list(enumerate(fail_probs))
        indexed.sort(key=lambda x: x[1], reverse=True)
        order = [i for i, _ in indexed]

        for idx in order:
            yield interface_pb2.PrioritizationReply(testId=test_cases[idx].testId)
