"""
Custom pygeoapi feature provider for SQLite sensor station data.
Implements basic querying of the stations table.
"""

import logging
import sqlite3

from pygeoapi.provider.base import BaseProvider

LOGGER = logging.getLogger(__name__)


class StationProvider(BaseProvider):
    """Provider for SQLite sensor station data."""

    def __init__(self, provider_def):
        super().__init__(provider_def)
        self.table = provider_def.get('table', 'stations')
        geom = provider_def.get('geometry', {})
        self.lon_field = geom.get('x_field', 'longitude')
        self.lat_field = geom.get('y_field', 'latitude')
        self.time_col = provider_def.get('time_field')
        self.get_fields()

    def get_fields(self):
        if self._fields:
            return self._fields
        conn = sqlite3.connect(self.data)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        results = cursor.execute(
            f'PRAGMA table_info({self.table})'
        ).fetchall()
        for item in results:
            if item['type'] in ['INTEGER', 'REAL']:
                self._fields[item['name']] = {'type': 'number'}
            elif item['type'].startswith('TEXT'):
                self._fields[item['name']] = {'type': 'string'}
        conn.close()
        return self._fields

    def _connect(self):
        conn = sqlite3.connect(self.data)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_feature(self, row, skip_geometry=False):
        row_dict = dict(row)
        props = {}
        geom_fields = {self.lon_field, self.lat_field}

        for key, value in row_dict.items():
            if key != self.id_field and key not in geom_fields:
                props[key] = value

        geometry = None
        if not skip_geometry:
            lon_val = row_dict.get(self.lon_field)
            lat_val = row_dict.get(self.lat_field)
            if lon_val is not None and lat_val is not None:
                geometry = {
                    'type': 'Point',
                    'coordinates': [float(lat_val), float(lon_val)],
                }

        return {
            'type': 'Feature',
            'id': str(row_dict[self.id_field]),
            'geometry': geometry,
            'properties': props,
        }

    def query(self, offset=0, limit=10, resulttype='results',
              bbox=[], datetime_=None, properties=[], sortby=[],
              select_properties=[], skip_geometry=False, q=None, **kwargs):

        conn = self._connect()
        cursor = conn.cursor()

        conditions = []
        params = []

        if bbox and len(bbox) >= 4:
            conditions.append(
                f'"{self.lat_field}" >= ? AND "{self.lat_field}" <= ? AND '
                f'"{self.lon_field}" >= ? AND "{self.lon_field}" <= ?'
            )
            params.extend([float(bbox[0]), float(bbox[2]),
                           float(bbox[1]), float(bbox[3])])

        if properties:
            for prop in properties:
                if isinstance(prop, (list, tuple)) and len(prop) == 2:
                    pname, pval = prop
                    conditions.append(f'"{pname}" = ?')
                    params.append(pval)

        where_clause = ''
        if conditions:
            where_clause = ' WHERE ' + ' AND '.join(conditions)

        cursor.execute(f'SELECT COUNT(*) FROM "{self.table}"')
        matched = cursor.fetchone()[0]

        feature_collection = {
            'type': 'FeatureCollection',
            'features': [],
            'numberMatched': matched,
            'numberReturned': 0,
        }

        sql = (
            f'SELECT * FROM "{self.table}"{where_clause}'
            f' ORDER BY "{self.id_field}" LIMIT ? OFFSET ?'
        )
        cursor.execute(sql, params + [limit, offset])
        rows = cursor.fetchall()

        features = [self._row_to_feature(row, skip_geometry) for row in rows]
        feature_collection['features'] = features
        feature_collection['numberReturned'] = len(features)

        conn.close()
        return feature_collection

    def get(self, identifier, **kwargs):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            f'SELECT * FROM "{self.table}" WHERE "{self.id_field}" = ?',
            [identifier],
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return self._row_to_feature(row)

    def __repr__(self):
        return f'<StationProvider> {self.data}'
