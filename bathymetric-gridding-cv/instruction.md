Ship track bathymetry observations are provided in `/app/data/ship_bathymetry.xyz` (tab-separated columns: longitude, latitude, depth in meters). The data covers region 245/255/20/30 with sparse, irregular sampling along ship tracks.

Build a data processing pipeline that optimizes GMT's spline tension parameter for gridding this data, using spatial cross-validation to prevent overfitting.

Your pipeline must:

- Preprocess the raw observations with `gmt blockmedian` at 10 arc-minute spacing within region 245/255/20/30
- Implement 4-fold spatial cross-validation by partitioning blocked data into quadrants split at longitude=250 and latitude=25 (SW, SE, NW, NE). For each candidate tension in `[0.0, 0.1, 0.25, 0.35, 0.5, 0.75, 1.0]`, hold out each quadrant in turn, grid the remaining 3 quadrants with `gmt surface`, sample the grid at held-out locations with `gmt grdtrack`, and compute RMSE. Select the tension with the lowest mean RMSE across all 4 folds.
- Create the final grid using `gmt surface` with the optimal tension over the full preprocessed dataset (region 245/255/20/30, 10 arc-minute spacing, gridline registration)
- Apply a Gaussian filter with 600 km full-width diameter using `gmt grdfilter` with flat-earth distance mode (`-D4`), then compute the residual grid (original minus smoothed) using `gmt grdmath`
- Extract a depth profile from (246, 22) to (254, 28) with exactly 50 equally-spaced sample points, computing along-track great-circle distances in km

Write output files to `/app/results/`:

- `cv_results.csv` — columns: `tension,mean_rmse` (7 rows, one per tension value)
- `optimal_tension.txt` — single float matching the CV-minimum tension
- `final_grid.nc` — gridded bathymetry in NetCDF format
- `grid_info.txt` — output of `gmt grdinfo` on the final grid
- `residual_stats.json` — keys: `mean`, `std`, `min`, `max`, `min_lon`, `min_lat`, `max_lon`, `max_lat`
- `profile.csv` — columns: `longitude,latitude,distance,depth` (50 rows)
- `profile_stats.json` — keys: `min_depth`, `max_depth`, `mean_depth`, `n_points`

GMT command-line tools are pre-installed. Python3 and pip are available. Install any additional Python packages you need.