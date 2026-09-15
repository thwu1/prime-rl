A C++ path tracer (C++11, CMake) is provided in `/app/`. It renders scenes with spheres, quads, and several material types (Lambertian, metal, dielectric, emissive), uses BVH acceleration, and writes PPM (P3) images to stdout. Source headers are in `/app/src/`.

Extend this renderer to support Constructive Solid Geometry (CSG). Create `/app/src/csg.h` implementing:

- `enum class csg_op` with values `union_op`, `intersection`, `difference`
- A `csg_node` class inheriting from `hittable`, constructable with `(shared_ptr<hittable> left, shared_ptr<hittable> right, csg_op op)`
- A `hit()` method that returns geometrically correct ray-surface intersections for the boolean-combined solid, including properly oriented outward-facing normals for all three operation types. Must handle rays originating from any position, including from inside child primitives (as occurs with refracted rays or secondary bounces).
- A `bounding_box()` returning a conservative AABB
- Full composability: `csg_node` instances must function correctly as children of other `csg_node` instances, enabling arbitrarily deep CSG trees

Update `/app/src/main.cc` to render a scene containing at least one CSG object of each operation type (union, intersection, difference) using overlapping spheres, plus at least one nested CSG object (a `csg_node` whose child is itself a `csg_node`). Call `srand(42)` before rendering, use image width 200, 10 samples per pixel, max depth 10.

Build: `cd /app && mkdir -p build && cd build && cmake .. && make`
Run: `./build/raytracer > output.ppm 2>/dev/null`