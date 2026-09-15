Survey points from five European national coordinate reference systems must be harmonized into ETRS89 geographic coordinates (EPSG:4258).

`/app/survey_data.csv` contains 10 survey points (columns: `point_id`, `epsg`, `easting`, `northing`) recorded in:

- **EPSG:27700** — OSGB36 / British National Grid
- **EPSG:28992** — Amersfoort / RD New
- **EPSG:31467** — DHDN / 3-degree Gauss-Kruger zone 3
- **EPSG:2154** — RGF93 v1 / Lambert-93
- **EPSG:25833** — ETRS89 / UTM zone 33N

These CRS use different national datums, ellipsoids, and map projections. Accurately transform all 10 points to ETRS89 geographic coordinates, determining the appropriate datum relationships and transformation parameters for each source CRS.

Produce `/app/results.json` conforming to the schema described in `/app/output_spec.json`. All geodesic computations (distances, polygon area) must use the GRS80 ellipsoid.

PROJ CLI tools (`cs2cs`, `cct`, `projinfo`, `geod`, `gie`) and Python 3 with pip are available.