"""Map loader for ROS2-compatible PGM + YAML map format.

"""

import numpy as np
import yaml
import os


class MapLoader:
    def __init__(self, yaml_path):
        with open(yaml_path) as f:
            meta = yaml.safe_load(f)

        self.resolution = meta['resolution']
        self.origin_x = meta['origin'][0]
        self.origin_y = meta['origin'][1]
        self.negate = meta.get('negate', 0)
        self.occupied_thresh = meta['occupied_thresh']
        self.free_thresh = meta['free_thresh']

        pgm_path = os.path.join(os.path.dirname(yaml_path), meta['image'])
        self.grid = self._load_pgm(pgm_path)
        self.height, self.width = self.grid.shape

    def _load_pgm(self, path):
        """Parse P5 (binary) PGM file into an integer occupancy grid."""
        with open(path, 'rb') as f:
            magic = f.readline().strip()
            if magic != b'P5':
                raise ValueError("Expected P5 PGM format, got {}".format(magic))

            line = f.readline()
            while line.startswith(b'#'):
                line = f.readline()

            width, height = map(int, line.split())
            maxval = int(f.readline().strip())
            data = f.read(width * height)

        pixels = np.frombuffer(data, dtype=np.uint8).reshape(height, width)
        pixels = np.flipud(pixels)

        if self.negate:
            occ_prob = pixels.astype(np.float64) / 255.0
        else:
            occ_prob = (255.0 - pixels.astype(np.float64)) / 255.0

        grid = np.zeros((height, width), dtype=np.int8)
        grid[occ_prob > self.occupied_thresh] = 100

        return grid

    def is_occupied(self, row, col):
        if 0 <= row < self.height and 0 <= col < self.width:
            return self.grid[row, col] >= 65
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
