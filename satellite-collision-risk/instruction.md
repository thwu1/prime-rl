A satellite conjunction analysis tool exists as a Maven project at `/app/`. It analyzes CCSDS Conjunction Data Message (CDM v1.0) files to assess collision risk between two space objects. The project has build configuration problems and incomplete/defective code. Get it building and passing all verification tests.

Pc quantifies the risk that two objects whose relative positions are uncertain will physically collide at closest approach, given a combined hard-body radius. In CDM mode, the tool must derive the encounter-plane parameters from the CDM file's raw state vectors and covariance data before computing Pc.

**Build**: `cd /app && mvn package -q` must produce a runnable JAR at `/app/target/conjanalysis-1.0.jar`.

**CDM mode**: `java -jar /app/target/conjanalysis-1.0.jar cdm <cdm_file> <combined_hbr_m> <output.json>` — JSON output:
```json
{"tca":"<str>", "miss_distance_m":<float>, "object1_name":"<str>", "object2_name":"<str>", "relative_velocity_km_s":<float>, "collision_probability":<float>, "risk_level":"<str>"}
```

**Direct mode**: `java -jar /app/target/conjanalysis-1.0.jar direct <xm> <ym> <sigma_x> <sigma_y> <radius> <output.json>` — all values in meters (miss vector components, standard deviations along principal axes, combined hard-body radius). JSON output:
```json
{"xm":<float>, "ym":<float>, "sigma_x":<float>, "sigma_y":<float>, "radius":<float>, "collision_probability":<float>, "risk_level":"<str>"}
```

**Risk levels**: HIGH (Pc >= 1e-4), MEDIUM (Pc >= 1e-7), LOW otherwise.

**Accuracy**: collision probability values must match validated reference cases spanning ~1e-27 to ~0.3 with relative error < 0.5%.

**Batch**: `/app/run.sh <file1> <file2> ...` must process CDM files, writing JSON results to stdout.

Source layout follows Maven conventions under `/app/src/`. CDM test data at `/app/data/`. All JSON floating-point values use full double precision.
