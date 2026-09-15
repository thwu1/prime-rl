"""SQLite database manager for pipeline intermediate state.

"""

import sqlite3
import json


class PipelineDB:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._init_schema()

    def _init_schema(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS costmap_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lethal_cell_count INTEGER,
            inflated_cell_count INTEGER,
            max_cost REAL,
            inflation_coverage_ratio REAL
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS route_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            waypoint_order TEXT,
            total_cost REAL,
            segment_costs TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS transform_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transform_key TEXT UNIQUE,
            x REAL,
            y REAL,
            theta REAL
        )''')
        self.conn.commit()

    def store_costmap_stats(self, lethal_count, inflated_count, max_cost, coverage):
        c = self.conn.cursor()
        c.execute(
            '''INSERT INTO costmap_stats
               (lethal_cell_count, inflated_cell_count, max_cost, inflation_coverage_ratio)
               VALUES (?, ?, ?, ?)''',
            (inflated_count, lethal_count, max_cost, coverage))
        self.conn.commit()

    def get_costmap_stats(self):
        c = self.conn.cursor()
        c.execute('''SELECT lethal_cell_count, inflated_cell_count,
                     max_cost, inflation_coverage_ratio
                     FROM costmap_stats ORDER BY id DESC LIMIT 1''')
        row = c.fetchone()
        if row:
            return {
                'lethal_cell_count': row[0],
                'inflated_cell_count': row[1],
                'max_cost': row[2],
                'inflation_coverage_ratio': row[3]
            }
        return None

    def store_route(self, waypoint_order, total_cost, segment_costs):
        c = self.conn.cursor()
        c.execute(
            'INSERT INTO route_data (waypoint_order, total_cost, segment_costs) VALUES (?, ?, ?)',
            (json.dumps(waypoint_order), total_cost, json.dumps(segment_costs)))
        self.conn.commit()

    def get_route(self):
        c = self.conn.cursor()
        c.execute('''SELECT waypoint_order, total_cost, segment_costs
                     FROM route_data ORDER BY id DESC LIMIT 1''')
        row = c.fetchone()
        if row:
            return {
                'waypoint_order': json.loads(row[0]),
                'total_cost': row[1],
                'segment_costs': json.loads(row[2])
            }
        return None

    def store_transform(self, key, x, y, theta):
        c = self.conn.cursor()
        c.execute(
            '''INSERT OR REPLACE INTO transform_results
               (transform_key, x, y, theta) VALUES (?, ?, ?, ?)''',
            (key, x, y, theta))
        self.conn.commit()

    def get_transform(self, key):
        c = self.conn.cursor()
        c.execute(
            'SELECT x, y, theta FROM transform_results WHERE transform_key = ?',
            (key,))
        row = c.fetchone()
        if row:
            return {'x': row[0], 'y': row[1], 'theta': row[2]}
        return None

    def close(self):
        self.conn.close()
