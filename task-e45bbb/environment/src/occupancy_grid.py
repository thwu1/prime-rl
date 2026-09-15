"""Occupancy grid map loader and coordinate conversion.

"""

import numpy as np
import json


class OccupancyGrid:
    def __init__(self, grid_path, meta_path):
        self.grid = np.load(grid_path)
        with open(meta_path) as f:
            meta = json.load(f)
        self.resolution = meta['resolution']
        self.origin_x = meta['origin'][0]
        self.origin_y = meta['origin'][1]
        self.width = meta['width']
        self.height = meta['height']
        self.occupied_thresh = meta['occupied_thresh']

    def is_occupied(self, row, col):
        if 0 <= row < self.height and 0 <= col < self.width:
            return self.grid[row, col] >= self.occupied_thresh
        return True

    def world_to_grid(self, world_x, world_y):
        """Convert world coordinates to grid (row, col)."""
        grid_col = int(round(world_x / self.resolution))
        grid_row = int(round(world_y / self.resolution))
        return grid_row, grid_col

    def grid_to_world(self, row, col):
        """Convert grid (row, col) to world coordinates."""
        world_x = col * self.resolution + self.origin_x
        world_y = row * self.resolution + self.origin_y
        return world_x, world_y
