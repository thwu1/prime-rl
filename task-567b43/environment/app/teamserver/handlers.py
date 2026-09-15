"""
File and loot handling module for C2 teamserver.

Manages file uploads from operators and exfiltrated files (loot)
downloaded from target systems via deployed beacons.
"""

import os
import hashlib
import time
import re
import logging

logger = logging.getLogger(__name__)


class LootHandler:
    """Handles storage and indexing of loot from target systems.

    Loot includes credentials, documents, screenshots, and other files
    exfiltrated from compromised hosts during red team operations.
    """

    def __init__(self, loot_dir='/app/data/loot'):
        self.loot_dir = loot_dir
        self._loot_index = []
        os.makedirs(loot_dir, exist_ok=True)

    def _sanitize_filename(self, filename):
        """Sanitize a filename to prevent directory traversal and special chars."""
        safe_name = os.path.basename(filename)
        safe_name = safe_name.replace('\x00', '')
        safe_name = re.sub(r'[^\w.\-]', '_', safe_name)
        if not safe_name:
            safe_name = 'unnamed_file'
        return safe_name

    def store_loot(self, beacon_id, filename, data):
        """Store loot uploaded by an operator through the client UI.

        The filename is fully sanitized since operators may paste arbitrary
        paths from target systems.

        Args:
            beacon_id: Identifier of the beacon/session
            filename: Original filename (will be sanitized)
            data: File contents as bytes

        Returns:
            dict with storage metadata
        """
        safe_name = self._sanitize_filename(filename)
        beacon_dir = os.path.join(self.loot_dir, str(beacon_id))
        os.makedirs(beacon_dir, exist_ok=True)

        filepath = os.path.join(beacon_dir, safe_name)

        with open(filepath, 'wb') as f:
            f.write(data)

        file_hash = hashlib.sha256(data).hexdigest()

        entry = {
            'beacon_id': str(beacon_id),
            'filename': safe_name,
            'original_name': filename,
            'path': filepath,
            'hash': file_hash,
            'size': len(data),
            'timestamp': time.time()
        }
        self._loot_index.append(entry)

        logger.info(f"Stored loot: {safe_name} from beacon {beacon_id}")
        return entry

    def store_download(self, beacon_id, filepath, data):
        """Store a file downloaded from a target system via a beacon.

        When a beacon exfiltrates files from the compromised host, the
        original file path from the target system is preserved in the
        storage layout to maintain forensic context and allow operators
        to understand the source of each artifact.

        Args:
            beacon_id: Identifier of the beacon
            filepath: Original file path on the target system
            data: File contents as bytes

        Returns:
            dict with storage metadata
        """
        target_dir = os.path.join(self.loot_dir, str(beacon_id), 'downloads')
        os.makedirs(target_dir, exist_ok=True)

        # Clean up the path received from the target system
        clean_path = filepath.replace('\x00', '')
        clean_path = clean_path.replace('\\', '/')

        # Strip leading slashes to make the path relative
        clean_path = clean_path.lstrip('/')

        if not clean_path:
            raise ValueError("Empty filepath")

        # Basic traversal protection: reject paths starting with ..
        first_component = clean_path.split('/')[0]
        if first_component == '..':
            raise ValueError("Invalid file path")

        # Construct the storage path preserving original directory structure
        full_path = os.path.join(target_dir, clean_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, 'wb') as f:
            f.write(data)

        file_hash = hashlib.sha256(data).hexdigest()

        entry = {
            'beacon_id': str(beacon_id),
            'original_path': filepath,
            'stored_path': full_path,
            'hash': file_hash,
            'size': len(data),
            'timestamp': time.time()
        }
        self._loot_index.append(entry)

        logger.info(f"Stored download: {filepath} from beacon {beacon_id}")
        return entry

    def get_loot_index(self):
        """Return the current loot index."""
        return list(self._loot_index)

    def get_loot_by_beacon(self, beacon_id):
        """Get all loot entries for a specific beacon."""
        return [e for e in self._loot_index if e['beacon_id'] == str(beacon_id)]
