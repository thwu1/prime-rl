# Road Curvature Analysis and Test Prioritization — Mathematical Framework

## 1. Domain Context

Self-driving car (SDC) simulation tests evaluate autonomous driving behavior on procedurally generated roads. Each road is a planar curve defined by a sequence of centerline coordinates. A simulation test **fails** when the vehicle deviates beyond the out-of-bound threshold — typically caused by excessive road curvature exceeding the controller's tracking capability.

Test prioritization reorders a test suite so that failure-inducing tests execute first, minimizing the cumulative cost to detect all faults during regression testing. The challenge lies in predicting which road geometries cause failures, given only geometric data and a training oracle.

## 2. Road Geometry and Curvature Theory

### 2.1 Coordinate Representation

A road is a discrete planar curve P = {(x₁,y₁), (x₂,y₂), ..., (xₙ,yₙ)} where consecutive points define line segments along the road centerline.

### 2.2 Discrete Curvature

The **heading angle** between consecutive points i and i+1:

    θᵢ = atan2(yᵢ₊₁ − yᵢ, xᵢ₊₁ − xᵢ)

The **angular change** between consecutive segments:

    Δθᵢ = adjust(θᵢ₊₁ − θᵢ)

where `adjust(α) = ((α + π) mod 2π) − π` wraps the angle difference to [−π, π].

The **arc length** of segment i:

    sᵢ = √((xᵢ₊₁ − xᵢ)² + (yᵢ₊₁ − yᵢ)²)

The **curvature** (inverse radius of curvature) at segment i:

    κᵢ = Δθᵢ / sᵢ

### 2.3 Curvature Profile

A road's **curvature profile** is the sequence {(κ₁, s₁), (κ₂, s₂), ..., (κₘ, sₘ)} where m = n − 2 (two fewer than the number of coordinate points, since curvature is defined at interior points). Together with the initial heading θ₀, this profile completely characterizes the road geometry up to rigid-body transformation.

### 2.4 Profile Approximation via Greedy Segment Merging

When curvature profiles have variable length or high dimensionality, they can be reduced to a fixed number N of representative segments through iterative greedy merging:

1. Initialize with the full profile {(κ₁, s₁), ..., (κₘ, sₘ)}.
2. While the number of segments exceeds N:
   - For each adjacent pair (j, j+1), compute the **merge candidate**:
     - κ_merged = (κⱼ · sⱼ + κⱼ₊₁ · sⱼ₊₁) / (sⱼ + sⱼ₊₁)  (arc-length-weighted average)
     - s_merged = sⱼ + sⱼ₊₁
   - Compute the **approximation error** of each merge as the sum of absolute deviations of all original sub-segments from the merged curvature, weighted by their arc lengths.
   - Execute the merge with minimum error.
3. The result is an N-segment approximation: {(κ'₁, s'₁), ..., (κ'ₙ, s'ₙ)}.

The feature vector for a road is then: [θ₀, κ'₁, ..., κ'ₙ, s'₁, ..., s'ₙ] ∈ ℝ^(2N+1).

### 2.5 Aggregate Curvature Features

Alternatively, the curvature profile can be summarized as aggregate statistics:
- **Total curvature**: Σ|Δθᵢ| (total angular change)
- **Maximum curvature**: max(|Δθᵢ|)
- **Mean curvature**: mean(|Δθᵢ|)
- **Curvature variance**: var(|Δθᵢ|)
- **Total arc length**: Σsᵢ
- **Sinuosity**: total_arc_length / direct_distance (ratio of road length to endpoint-to-endpoint distance)
- **Sharp turn count**: number of segments where |Δθᵢ| exceeds a threshold

These features capture global road difficulty characteristics that correlate with simulation failures. Roads with higher curvature, more sharp turns, or greater sinuosity tend to challenge the autonomous driving controller more severely.

## 3. Evaluation Metrics

### 3.1 APFD — Average Percentage of Faults Detected

Given a prioritized ordering of n tests containing m faults at 1-indexed positions p₁, p₂, ..., pₘ:

    APFD = 1 − (Σᵢ pᵢ) / (n · m) + 1 / (2n)

- Range: [0, 1]. Higher is better.
- Random baseline: ≈ 0.5 + 1/(2n).
- Optimal (all faults first): 1 − (m+1)/(2n).

### 3.2 APFDc — Cost-Weighted APFD

Incorporates test execution duration. For each fault j in the ordering, let cⱼ be the cumulative execution time up to and including that fault. Let C be the total execution time of all tests:

    APFDc = 1 − (Σⱼ cⱼ) / (C · m) + 1 / (2m)

- Range: [0, 1]. Higher is better.
- Prioritizing cheap failing tests improves APFDc.
- APFDc can diverge from APFD when test durations vary — a prioritizer must understand the tension between ranking by failure probability alone versus ranking by expected cost-to-failure.

### 3.3 Time-to-First-Fault (TTFF)

    TTFF = Σ duration(tⱼ) for j = 1, ..., k

where k is the position of the first fault in the ordering. Measures how quickly the first failure is detected. Lower is better.

### 3.4 Time-to-Last-Fault (TTLF)

    TTLF = Σ duration(tⱼ) for j = 1, ..., k

where k is the position of the last fault in the ordering. Measures when ALL faults have been detected. Lower is better.

**Trade-off insight**: Optimizing TTFF favors placing any likely failure first (even an expensive one), while optimizing TTLF requires ALL failures to cluster early. APFD balances average detection, while APFDc weights by cost. An effective prioritizer must reason about all four metrics holistically.

## 4. gRPC Competition Interface

The `CompetitionTool` service is defined in `interface.proto`:

- **Name(Empty) → NameReply**: Returns the tool's identifier string.
- **Initialize(stream Oracle) → InitializationReply**: Client-streaming RPC. Each `Oracle` message contains a `testCase` (with `testId` and `roadPoints`) and a `hasFailed` boolean. This is the training oracle — the server should learn patterns that predict failure. Returns `ok=true` on success.
- **Prioritize(stream SDCTestCase) → stream PrioritizationReply**: Bidirectional streaming RPC. The client streams unlabeled `SDCTestCase` messages. The server must consume the entire stream before yielding `PrioritizationReply` messages, since producing a global ordering requires seeing all candidates. Each reply contains a `testId` — the ordering of replies defines the prioritization (tests likely to fail should appear first).

## 5. Data Format

### Training Data (`train_data.json`)

```json
[
  {
    "_id": {"$oid": "<24-char hex>"},
    "meta_data": {
      "test_info": {
        "test_outcome": "FAIL" | "PASS",
        "test_duration": <float, seconds>
      }
    },
    "road_points": [{"x": <float>, "y": <float>}, ...]
  }
]
```

### Test Data (`test_data.json`)

```json
[
  {
    "_id": {"$oid": "<24-char hex>"},
    "road_points": [{"x": <float>, "y": <float>}, ...]
  }
]
```

## 6. Output Specification

Write `/app/results.json`:

```json
{
  "tool_name": "<name returned by the Name RPC>",
  "train_size": <int>,
  "test_size": <int>,
  "prioritized_order": ["<testId_1>", "<testId_2>", ...],
  "apfd": <float, estimated APFD>,
  "apfdc": <float, estimated APFDc>
}
```

The `prioritized_order` array must contain every test ID from `test_data.json` exactly once. Since ground truth labels are unavailable for the test set, the reported `apfd` and `apfdc` values are the solver's best estimates (e.g., via cross-validation on training data or model confidence).
