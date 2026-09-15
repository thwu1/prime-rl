#!/usr/bin/env python3
"""
Create damaged BagIt bags for the forensic recovery task.

Each archive contains a bag with specific, known violations of RFC 8493.
The agent must extract, diagnose, repair, and re-serialize these bags.

"""
import hashlib
import io
import os
import tarfile

ARCHIVES_DIR = "/app/damaged-archives"


def sha256hex(data):
    return hashlib.sha256(data).hexdigest()


def sha512hex(data):
    return hashlib.sha512(data).hexdigest()


def md5hex(data):
    return hashlib.md5(data).hexdigest()


def add_to_tar(tar, arcname, data):
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def create_research_dataset():
    """Bag 1: BOM in bagit.txt, wrong SHA-256 checksum, whitespace before colon.
    Properly serialized, version 0.97."""
    files = {
        "data/readme.txt": b"Research dataset documentation\n",
        "data/results.csv": b"id,value\n1,42\n2,17\n3,99\n",
        "data/notes.txt": b"Additional notes about the research.\n",
    }
    hashes = {p: sha256hex(d) for p, d in files.items()}

    # DAMAGE 1: UTF-8 BOM prepended to bagit.txt
    bom = b"\xef\xbb\xbf"
    bagit = bom + b"BagIt-Version: 0.97\nTag-File-Character-Encoding: UTF-8\n"

    # DAMAGE 2: wrong checksum for results.csv
    bad_hashes = dict(hashes)
    bad_hashes["data/results.csv"] = "0" * 64
    manifest = "".join(f"{h}  {p}\n" for p, h in sorted(bad_hashes.items()))

    # DAMAGE 3: whitespace before colon in bag-info.txt
    baginfo = b"Source-Organization : Library of Congress\nBagging-Date: 2024-01-15\n"

    path = os.path.join(ARCHIVES_DIR, "research-dataset.tar.gz")
    with tarfile.open(path, "w:gz") as tar:
        pfx = "research-dataset/"
        add_to_tar(tar, pfx + "bagit.txt", bagit)
        add_to_tar(tar, pfx + "manifest-sha256.txt", manifest.encode())
        add_to_tar(tar, pfx + "bag-info.txt", baginfo)
        for fp, fd in sorted(files.items()):
            add_to_tar(tar, pfx + fp, fd)


def create_photo_collection():
    """Bag 2: Wrong serialization (no top-level dir), extra payload file not
    in manifest. Version 0.97."""
    files = {
        "data/photo1.dat": b"FAKE_JPEG_DATA_PHOTO_1\n",
        "data/photo2.dat": b"FAKE_JPEG_DATA_PHOTO_2\n",
        "data/photo3.dat": b"FAKE_JPEG_DATA_PHOTO_3\n",
    }
    hashes = {p: sha256hex(d) for p, d in files.items()}

    bagit = b"BagIt-Version: 0.97\nTag-File-Character-Encoding: UTF-8\n"

    # DAMAGE 1: manifest only lists photo1 and photo2 (photo3 is extra)
    manifest = (
        f"{hashes['data/photo1.dat']}  data/photo1.dat\n"
        f"{hashes['data/photo2.dat']}  data/photo2.dat\n"
    )
    baginfo = b"Source-Organization: Photo Archive\nBagging-Date: 2024-02-20\n"

    path = os.path.join(ARCHIVES_DIR, "photo-collection.tar.gz")
    with tarfile.open(path, "w:gz") as tar:
        # DAMAGE 2: NO top-level directory (flat serialization)
        add_to_tar(tar, "bagit.txt", bagit)
        add_to_tar(tar, "manifest-sha256.txt", manifest.encode())
        add_to_tar(tar, "bag-info.txt", baginfo)
        for fp, fd in sorted(files.items()):
            add_to_tar(tar, fp, fd)


def create_audio_archive():
    """Bag 3: Path traversal in fetch.txt and manifest, duplicate entry with
    conflicting hash. Version 0.97."""
    files = {
        "data/track1.wav": b"FAKE_AUDIO_DATA_TRACK_1\n",
        "data/track2.wav": b"FAKE_AUDIO_DATA_TRACK_2\n",
    }
    hashes = {p: sha256hex(d) for p, d in files.items()}

    bagit = b"BagIt-Version: 0.97\nTag-File-Character-Encoding: UTF-8\n"

    # DAMAGE 1 & 2: traversal path + duplicate entry with wrong hash
    wrong_hash = "a" * 64
    traversal_hash = "b" * 64
    manifest = (
        f"{hashes['data/track1.wav']}  data/track1.wav\n"
        f"{wrong_hash}  data/track1.wav\n"
        f"{hashes['data/track2.wav']}  data/track2.wav\n"
        f"{traversal_hash}  data/../../../tmp/evil\n"
    )

    # DAMAGE 3: fetch.txt with path traversal
    fetch = b"https://example.com/evil.wav 999 data/../../../tmp/evil\n"
    baginfo = b"Source-Organization: Audio Lab\nBagging-Date: 2024-03-10\n"

    path = os.path.join(ARCHIVES_DIR, "audio-archive.tar.gz")
    with tarfile.open(path, "w:gz") as tar:
        pfx = "audio-archive/"
        add_to_tar(tar, pfx + "bagit.txt", bagit)
        add_to_tar(tar, pfx + "manifest-sha256.txt", manifest.encode())
        add_to_tar(tar, pfx + "bag-info.txt", baginfo)
        add_to_tar(tar, pfx + "fetch.txt", fetch)
        for fp, fd in sorted(files.items()):
            add_to_tar(tar, pfx + fp, fd)


def create_manuscript_collection():
    """Bag 4: Version 0.93 missing encoding line, two manifests with different
    file sets, extra payload file in none. Needs full v1.0 migration."""
    files = {
        "data/page1.tiff": b"FAKE_TIFF_DATA_PAGE_1\n",
        "data/page2.tiff": b"FAKE_TIFF_DATA_PAGE_2\n",
        "data/page3.tiff": b"FAKE_TIFF_DATA_PAGE_3\n",
        "data/page4.tiff": b"FAKE_TIFF_DATA_PAGE_4\n",
    }
    md5s = {p: md5hex(d) for p, d in files.items()}
    sha512s = {p: sha512hex(d) for p, d in files.items()}

    # DAMAGE 1: missing Tag-File-Character-Encoding line
    bagit = b"BagIt-Version: 0.93\n"

    # DAMAGE 2: manifests list DIFFERENT file sets
    manifest_md5 = (
        f"{md5s['data/page1.tiff']}  data/page1.tiff\n"
        f"{md5s['data/page2.tiff']}  data/page2.tiff\n"
    )
    manifest_sha512 = (
        f"{sha512s['data/page1.tiff']}  data/page1.tiff\n"
        f"{sha512s['data/page3.tiff']}  data/page3.tiff\n"
    )
    # DAMAGE 3: data/page4.tiff exists but is not in ANY manifest
    baginfo = b"Source-Organization: Manuscript Archive\nBagging-Date: 2024-04-05\n"

    path = os.path.join(ARCHIVES_DIR, "manuscript-collection.tar.gz")
    with tarfile.open(path, "w:gz") as tar:
        pfx = "manuscript-collection/"
        add_to_tar(tar, pfx + "bagit.txt", bagit)
        add_to_tar(tar, pfx + "manifest-md5.txt", manifest_md5.encode())
        add_to_tar(tar, pfx + "manifest-sha512.txt", manifest_sha512.encode())
        add_to_tar(tar, pfx + "bag-info.txt", baginfo)
        for fp, fd in sorted(files.items()):
            add_to_tar(tar, pfx + fp, fd)


if __name__ == "__main__":
    os.makedirs(ARCHIVES_DIR, exist_ok=True)
    create_research_dataset()
    create_photo_collection()
    create_audio_archive()
    create_manuscript_collection()
    print(f"Created 4 damaged archives in {ARCHIVES_DIR}")
