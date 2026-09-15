
"""
Fixed custom pygeoapi feature provider for SQLite sensor station data.
Implements the full BaseProvider contract including spatial/temporal
filtering, property filtering, pagination, CRS transform, and
transactional CRUD operations.
"""

import json
import logging
import sqlite3

from pygeoapi.provider.base import BaseProvider, ProviderItemNotFoundError

LOGGER = logging.getLogger(__name__)

try:
    from pygeoapi.crs import crs_transform
except ImportError:
    def crs_transform(func):
        return func


class StationProvider(BaseProvider):
    """Custom pygeoapi feature provider for SQLite sensor station data."""

    def __init__(self, provider_def):
        super().__init__(provider_def)
        self.table = provider_def.get('table', 'stations')

        geom = provider_def.get('geometry', {})
        self.lon_field = geom.get('x_field', 'longitude')
        self.lat_field = geom.get('y_field', 'latitude')
        self.time_col = provider_def.get('time_field', 'observation_time')
        self.id_field = provider_def.get('id_field', 'id')

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

    def _build_where(self, bbox=None, datetime_=None, properties=None):
        conditions = []
        params = []

        if bbox and len(bbox) >= 4:
            minx = float(bbox[0])
            miny = float(bbox[1])
            maxx = float(bbox[2])
            maxy = float(bbox[3])
            conditions.append(
                f'"{self.lon_field}" >= ? AND "{self.lon_field}" <= ? AND '
                f'"{self.lat_field}" >= ? AND "{self.lat_field}" <= ?'
            )
            params.extend([minx, maxx, miny, maxy])

        if properties:
            for prop in properties:
                if isinstance(prop, (list, tuple)) and len(prop) == 2:
                    pname, pval = prop
                else:
                    continue
                conditions.append(f'"{pname}" = ?')
                params.append(pval)

        if datetime_ and self.time_col:
            if '/' in datetime_:
                parts = datetime_.split('/')
                start = parts[0] if parts[0] not in ('..', '') else None
                end = parts[1] if parts[1] not in ('..', '') else None
                if start:
                    conditions.append(f'"{self.time_col}" >= ?')
                    params.append(start)
                if end:
                    conditions.append(f'"{self.time_col}" <= ?')
                    params.append(end)
            else:
                conditions.append(f'"{self.time_col}" = ?')
                params.append(datetime_)

        return conditions, params

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
                    'coordinates': [float(lon_val), float(lat_val)],
                }

        return {
            'type': 'Feature',
            'id': str(row_dict[self.id_field]),
            'geometry': geometry,
            'properties': props,
        }

    @crs_transform
    def query(self, offset=0, limit=10, resulttype='results',
              bbox=[], datetime_=None, properties=[], sortby=[],
              select_properties=[], skip_geometry=False, q=None, **kwargs):

        conn = self._connect()
        cursor = conn.cursor()

        conditions, params = self._build_where(bbox, datetime_, properties)
        where_clause = ''
        if conditions:
            where_clause = ' WHERE ' + ' AND '.join(conditions)

        cursor.execute(
            f'SELECT COUNT(*) FROM "{self.table}"{where_clause}', params
        )
        matched = cursor.fetchone()[0]

        feature_collection = {
            'type': 'FeatureCollection',
            'features': [],
            'numberMatched': matched,
            'numberReturned': 0,
        }

        if resulttype == 'hits':
            conn.close()
            return feature_collection

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

    @crs_transform
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
            raise ProviderItemNotFoundError(f'Item {identifier} not found')

        return self._row_to_feature(row)

    def _parse_feature(self, data):
        """Parse incoming feature data from bytes/str/dict."""
        if isinstance(data, (bytes, str)):
            data = json.loads(data)
        return data

    def create(self, new_feature):
        new_feature = self._parse_feature(new_feature)
        props = new_feature.get('properties', {})
        geom = new_feature.get('geometry', {})

        conn = self._connect()
        cursor = conn.cursor()

        cursor.execute(
            f'SELECT MAX("{self.id_field}") FROM "{self.table}"'
        )
        max_id = cursor.fetchone()[0] or 0
        new_id = max_id + 1

        columns = [self.id_field]
        values = [new_id]

        if geom and 'coordinates' in geom:
            columns.extend([self.lon_field, self.lat_field])
            values.extend([geom['coordinates'][0], geom['coordinates'][1]])

        for key, value in props.items():
            columns.append(key)
            values.append(value)

        placeholders = ', '.join(['?' for _ in columns])
        col_str = ', '.join([f'"{c}"' for c in columns])

        cursor.execute(
            f'INSERT INTO "{self.table}" ({col_str}) VALUES ({placeholders})',
            values,
        )
        conn.commit()
        conn.close()
        return str(new_id)

    def update(self, identifier, new_feature):
        new_feature = self._parse_feature(new_feature)
        props = new_feature.get('properties', {})
        geom = new_feature.get('geometry')

        conn = self._connect()
        cursor = conn.cursor()

        sets = []
        values = []

        if geom and 'coordinates' in geom:
            sets.append(f'"{self.lon_field}" = ?')
            values.append(geom['coordinates'][0])
            sets.append(f'"{self.lat_field}" = ?')
            values.append(geom['coordinates'][1])

        for key, value in props.items():
            sets.append(f'"{key}" = ?')
            values.append(value)

        if not sets:
            conn.close()
            return True

        values.append(identifier)
        set_str = ', '.join(sets)
        cursor.execute(
            f'UPDATE "{self.table}" SET {set_str}'
            f' WHERE "{self.id_field}" = ?',
            values,
        )
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def delete(self, identifier):
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            f'DELETE FROM "{self.table}" WHERE "{self.id_field}" = ?',
            [identifier],
        )
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected > 0

    def __repr__(self):
        return f'<StationProvider> {self.data}'
