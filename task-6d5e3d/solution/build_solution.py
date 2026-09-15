#!/usr/bin/env python3

"""
Deploys the fixed pygeoapi provider plugin and writes the corrected
configuration. Replaces the broken provider and config with working versions.
"""

import os
import shutil

PLUGIN_DIR = "/app/plugins"
PROVIDER_SRC = "/solution/station_provider.py"
PROVIDER_DST = os.path.join(PLUGIN_DIR, "station_provider.py")
CONFIG_FILE = "/app/config.yml"


CONFIG = """\
server:
    bind:
        host: 0.0.0.0
        port: 5000
    url: http://localhost:5000/
    mimetype: application/json; charset=UTF-8
    encoding: utf-8
    gzip: false
    language: en-US
    cors: true
    pretty_print: true
    limits:
        default_items: 10
        max_items: 100
    map:
        url: https://tile.openstreetmap.org/{z}/{x}/{y}.png
        attribution: '&copy; <a href="https://openstreetmap.org/copyright">OpenStreetMap contributors</a>'
    manager:
        name: TinyDB
        connection: /tmp/pygeoapi-process-manager.db
        output_dir: /tmp/

logging:
    level: ERROR

metadata:
    identification:
        title: Meteorological Sensor Stations API
        description: OGC API providing access to global meteorological sensor station data
        keywords:
            - meteorology
            - sensors
            - stations
        keywords_type: theme
        terms_of_service: https://creativecommons.org/licenses/by/4.0/
        url: http://example.org
    license:
        name: CC-BY 4.0 license
        url: https://creativecommons.org/licenses/by/4.0/
    provider:
        name: Weather Data Organization
        url: https://example.org
    contact:
        name: Admin
        position: Data Manager
        email: admin@example.org
        role: pointOfContact

resources:
    stations:
        type: collection
        title: Meteorological Sensor Stations
        description: Global meteorological sensor station data with 25 stations
        keywords:
            - meteorology
            - sensors
            - stations
            - weather
        extents:
            spatial:
                bbox: [-180, -90, 180, 90]
                crs: http://www.opengis.net/def/crs/OGC/1.3/CRS84
            temporal:
                begin: 2024-01-01T00:00:00Z
                end: 2024-12-31T23:59:59Z
        providers:
            - type: feature
              name: station_provider.StationProvider
              data: /app/data/stations.db
              table: stations
              id_field: id
              time_field: observation_time
              geometry:
                  x_field: longitude
                  y_field: latitude
              editable: true
              crs:
                  - http://www.opengis.net/def/crs/OGC/1.3/CRS84
                  - http://www.opengis.net/def/crs/EPSG/0/4326
                  - http://www.opengis.net/def/crs/EPSG/0/3857
              storage_crs: http://www.opengis.net/def/crs/OGC/1.3/CRS84
"""


def main():
    print("=== Deploying fixed provider plugin ===")
    os.makedirs(PLUGIN_DIR, exist_ok=True)
    shutil.copy2(PROVIDER_SRC, PROVIDER_DST)
    print(f"Copied fixed provider to {PROVIDER_DST}")

    print("=== Writing corrected pygeoapi configuration ===")
    with open(CONFIG_FILE, "w") as f:
        f.write(CONFIG)
    print(f"Wrote corrected config to {CONFIG_FILE}")

    print("=== Done ===")


if __name__ == "__main__":
    main()
