"""Generate the warehouse occupancy grid map.

Run during Docker build to create deterministic map data.
"""

import numpy as np
import json
import os

os.makedirs('/app/map', exist_ok=True)

# Create 50x50 occupancy grid
# 0 = free, 100 = occupied
grid = np.zeros((50, 50), dtype=np.int8)

# Perimeter walls
grid[0, :] = 100
grid[49, :] = 100
grid[:, 0] = 100
grid[:, 49] = 100

# Horizontal barrier 1: rows 15-16, cols 5-35 (gap at cols 36-48)
grid[15:17, 5:36] = 100

# Horizontal barrier 2: rows 33-34, cols 15-45 (gap at cols 1-14)
grid[33:35, 15:45] = 100

# Obstacle block: rows 23-26, cols 23-26
grid[23:27, 23:27] = 100

# Small obstacles
grid[8:10, 20:22] = 100
grid[40:42, 35:37] = 100

np.save('/app/map/warehouse_grid.npy', grid)

# Map metadata
metadata = {
    'resolution': 0.1,
    'origin': [-2.5, -2.5, 0.0],
    'width': 50,
    'height': 50,
    'occupied_thresh': 65,
    'free_thresh': 25
}

with open('/app/map/warehouse_meta.json', 'w') as f:
    json.dump(metadata, f, indent=2)

print(f"Map generated: {grid.shape}, {int(np.sum(grid >= 65))} occupied cells")
