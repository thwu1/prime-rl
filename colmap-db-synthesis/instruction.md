A COLMAP sparse reconstruction in text format is provided at `/app/sparse/`, containing `cameras.txt`, `images.txt`, and `points3D.txt`. The reconstruction uses multiple camera models across six images with 15 triangulated 3D points.

Produce two output files:

**1. `/app/database.db`** — A COLMAP-compatible SQLite database that faithfully represents all reconstruction data using COLMAP's native database schema and binary encoding conventions. The database must include: camera intrinsic definitions, registered images with their pose priors, observed keypoint locations, placeholder descriptors, feature matches derived from 3D point co-visibility tracks, and placeholder two-view geometry entries for each matched pair. The database must be byte-compatible with COLMAP's own database reader — same schema, same binary packing, same identifier conventions.

**2. `/app/report.json`** — A JSON analysis report containing:
- `"camera_centers"`: dict mapping image ID (string) to `[x, y, z]` world-space camera position for each image
- `"pair_matches"`: dict mapping the database pair identifier (string) to the number of feature matches for that image pair
- `"track_length_histogram"`: dict mapping track length (string) to the count of 3D points with that track length

COLMAP's source code and documentation at https://colmap.github.io are the authoritative references for all schema details, binary formats, identifier conventions, and geometric conventions.