A 2D vector rendering pipeline needs a production-quality cubic Bezier curve flattener that is substantially more efficient than naive recursive subdivision while maintaining strict approximation guarantees. Design and implement this flattener.

Create `/app/flattener.py` exporting:

```python
flatten_cubic(p0, p1, p2, p3, tolerance=0.25) -> list[tuple[float, float]]
```

where `p0`-`p3` are `Vec2` control points (from `/app/geometry.py`) and the return value is a polyline approximating the cubic curve.

The polyline must satisfy all of the following:

- **Accuracy**: the maximum distance from any point on the original cubic to the nearest polyline segment does not exceed `tolerance`.
- **Efficiency**: for curves with non-trivial curvature at tight tolerances, the output must contain substantially fewer segments than the naive recursive subdivision baseline in `/app/naive_flatten.py`.
- **Robustness**: degenerate inputs (self-intersecting curves, zero-length curves, coincident control points, near-zero derivatives at endpoints) must be handled without crashes, NaN values, or unbounded output.
- **Scaling**: tighter tolerances must produce more segments.
- **Endpoints**: the first output point must equal `(p0.x, p0.y)` and the last must equal `(p3.x, p3.y)`.

Files in `/app/`:
- `geometry.py` -- `Vec2` class, `eval_cubic()`, `max_error_to_polyline()`
- `naive_flatten.py` -- baseline recursive subdivision flattener
- `reference/` -- supplementary Rust source code (buildable with `cargo build`)