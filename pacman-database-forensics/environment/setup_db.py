#!/usr/bin/env python3
"""Generate a simulated corrupted pacman database for the forensics task.

Creates a realistic pacman local+sync database with ~30 packages and multiple
planted issues across 6 categories. The sync database is stored as a
zstd-compressed tar archive (pacman's native format). A SQLite metadata cache
provides package size and repository state information.
"""
import io
import os
import sqlite3
import subprocess
import tarfile

ARCHROOT = "/app/archroot"
LOCAL_DB = os.path.join(ARCHROOT, "var/lib/pacman/local")
SYNC_DIR = os.path.join(ARCHROOT, "var/lib/pacman/sync")

# ---------------------------------------------------------------------------
# Package definitions
# ---------------------------------------------------------------------------

PACKAGES = [
    # ---- Core layer ----
    {
        "name": "linux-api-headers",
        "local_ver": "6.8-1",
        "sync_ver": "6.8-1",
        "desc": "Kernel headers sanitized for use in userspace",
        "url": "https://www.gnu.org/software/libc",
        "deps": [],
        "provides": [],
        "files": [
            "usr/", "usr/include/", "usr/include/linux/",
            "usr/include/linux/types.h", "usr/include/linux/version.h",
        ],
        "reason": 1,
        "size": 1286144,
    },
    {
        "name": "filesystem",
        "local_ver": "2024.04.07-1",
        "sync_ver": "2024.04.07-1",
        "desc": "Base Arch Linux files",
        "url": "https://archlinux.org",
        "deps": [],
        "provides": [],
        "files": [
            "etc/", "etc/fstab", "etc/group", "etc/hosts", "etc/passwd",
            "usr/", "usr/bin/", "usr/lib/", "usr/share/",
        ],
        "reason": 0,
        "size": 2048,
    },
    {
        "name": "glibc",
        "local_ver": "2.39-1",
        "sync_ver": "2.39-1",
        "desc": "GNU C Library",
        "url": "https://www.gnu.org/software/libc",
        "deps": ["linux-api-headers>=6.2", "filesystem"],
        "provides": ["libm.so=6-64", "libc.so=6-64", "libdl.so=2-64", "libpthread.so=0-64"],
        "files": [
            "usr/", "usr/lib/", "usr/lib/libc.so.6", "usr/lib/libm.so.6",
            "usr/lib/ld-linux-x86-64.so.2",
        ],
        "reason": 0,
        "size": 44892160,
    },
    {
        "name": "gcc-libs",
        "local_ver": "14.1.1-1",
        "sync_ver": "14.1.1-1",
        "desc": "Runtime libraries shipped by GCC",
        "url": "https://gcc.gnu.org",
        "deps": ["glibc>=2.39"],
        "provides": ["libstdc++.so=6-64", "libgcc_s.so=1-64"],
        "files": [
            "usr/", "usr/lib/", "usr/lib/libstdc++.so.6",
            "usr/lib/libgcc_s.so.1",
        ],
        "reason": 0,
        "size": 12582912,
    },
    # ncurses -- PARTIAL UPGRADE  (local 6.3-1, sync 6.4-3)
    {
        "name": "ncurses",
        "local_ver": "6.3-1",
        "sync_ver": "6.4-3",
        "desc": "System V Release 4.0 curses emulation library",
        "url": "https://invisible-island.net/ncurses",
        "deps": ["glibc", "gcc-libs"],
        "provides": ["libncursesw.so=6-64"],
        "files": [
            "usr/", "usr/lib/", "usr/lib/libncursesw.so.6",
            "usr/lib/libncurses.so.6", "usr/share/", "usr/share/terminfo/",
        ],
        "reason": 0,
        "size": 2408448,
    },
    # readline -- MISSING DESC
    {
        "name": "readline",
        "local_ver": "8.2.010-1",
        "sync_ver": "8.2.010-1",
        "desc": "GNU readline library",
        "url": "https://tiswww.case.edu/php/chet/readline/rltop.html",
        "deps": ["glibc", "ncurses>=6.4"],
        "provides": ["libreadline.so=8-64"],
        "files": [
            "usr/", "usr/lib/", "usr/lib/libreadline.so.8",
            "usr/lib/libhistory.so.8",
        ],
        "reason": 0,
        "size": 491520,
        "missing_desc": True,
    },
    # bash
    {
        "name": "bash",
        "local_ver": "5.2.026-1",
        "sync_ver": "5.2.026-1",
        "desc": "The GNU Bourne Again shell",
        "url": "https://www.gnu.org/software/bash",
        "deps": ["readline", "glibc", "ncurses>=6.4"],
        "provides": [],
        "files": ["usr/", "usr/bin/", "usr/bin/bash", "usr/bin/sh"],
        "reason": 0,
        "size": 9261056,
    },
    # zlib
    {
        "name": "zlib",
        "local_ver": "1.3.1-1",
        "sync_ver": "1.3.1-1",
        "desc": "Compression library implementing the deflate compression method",
        "url": "https://www.zlib.net",
        "deps": ["glibc"],
        "provides": ["libz.so=1-64"],
        "files": [
            "usr/", "usr/lib/", "usr/lib/libz.so.1", "usr/lib/libz.so",
        ],
        "reason": 0,
        "size": 327680,
    },
    # xz
    {
        "name": "xz",
        "local_ver": "5.6.2-1",
        "sync_ver": "5.6.2-1",
        "desc": "Library and command line tools for XZ and LZMA compressed files",
        "url": "https://tukaani.org/xz",
        "deps": ["glibc"],
        "provides": ["liblzma.so=5-64"],
        "files": [
            "usr/", "usr/bin/", "usr/bin/xz",
            "usr/lib/", "usr/lib/liblzma.so.5",
        ],
        "reason": 0,
        "size": 1048576,
    },
    # bzip2
    {
        "name": "bzip2",
        "local_ver": "1.0.8-5",
        "sync_ver": "1.0.8-5",
        "desc": "A high-quality data compression program",
        "url": "https://sourceware.org/bzip2",
        "deps": ["glibc"],
        "provides": [],
        "files": [
            "usr/", "usr/bin/", "usr/bin/bzip2",
            "usr/lib/", "usr/lib/libbz2.so.1",
        ],
        "reason": 0,
        "size": 327680,
    },
    # zstd
    {
        "name": "zstd",
        "local_ver": "1.5.6-1",
        "sync_ver": "1.5.6-1",
        "desc": "Zstandard - Fast real-time compression algorithm",
        "url": "https://facebook.github.io/zstd",
        "deps": ["glibc", "zlib"],
        "provides": ["libzstd.so=1-64"],
        "files": [
            "usr/", "usr/bin/", "usr/bin/zstd",
            "usr/lib/", "usr/lib/libzstd.so.1",
        ],
        "reason": 0,
        "size": 1572864,
    },

    # ---- ICU / XML layer (epoch-based versioning) ----
    # icu -- PARTIAL UPGRADE with epoch (local 1:74.2-1, sync 1:75.1-1)
    {
        "name": "icu",
        "local_ver": "1:74.2-1",
        "sync_ver": "1:75.1-1",
        "desc": "International Components for Unicode library",
        "url": "https://icu.unicode.org",
        "deps": ["glibc", "gcc-libs"],
        "provides": ["libicuuc.so=74-64", "libicui18n.so=74-64", "libicudata.so=74-64"],
        "files": [
            "usr/", "usr/lib/", "usr/lib/libicuuc.so.74",
            "usr/lib/libicui18n.so.74", "usr/lib/libicudata.so.74",
        ],
        "reason": 0,
        "size": 34603008,
    },
    # libxml2 -- depends on icu>=1:75.0 (affected by icu partial upgrade)
    {
        "name": "libxml2",
        "local_ver": "2.12.7-1",
        "sync_ver": "2.12.7-1",
        "desc": "XML C parser and toolkit",
        "url": "https://gitlab.gnome.org/GNOME/libxml2",
        "deps": ["glibc", "icu>=1:75.0", "zlib", "xz"],
        "provides": ["libxml2.so=2-64"],
        "files": [
            "usr/", "usr/lib/", "usr/lib/libxml2.so.2",
            "usr/bin/", "usr/bin/xmllint",
        ],
        "reason": 0,
        "size": 1572864,
    },
    # libtasn1 -- EPOCH TRAP: local 1:4.19.0-1 is NEWER than sync 4.20.0-1
    # (epoch 1 > epoch 0, despite lower version number)
    {
        "name": "libtasn1",
        "local_ver": "1:4.19.0-1",
        "sync_ver": "4.20.0-1",
        "desc": "Implementation of the Distinguished Encoding Rules (DER) parser",
        "url": "https://www.gnu.org/software/libtasn1",
        "deps": ["glibc"],
        "provides": ["libtasn1.so=6-64"],
        "files": [
            "usr/", "usr/lib/", "usr/lib/libtasn1.so.6",
        ],
        "reason": 1,
        "size": 196608,
    },
    # p11-kit -- depends on libtasn1>=4.20.0 (satisfied by epoch)
    {
        "name": "p11-kit",
        "local_ver": "0.25.3-1",
        "sync_ver": "0.25.3-1",
        "desc": "Provides a way to load and enumerate PKCS#11 modules",
        "url": "https://p11-glue.github.io/p11-glue/p11-kit.html",
        "deps": ["glibc", "libtasn1>=4.20.0"],
        "provides": [],
        "files": [
            "usr/", "usr/lib/", "usr/lib/libp11-kit.so.0",
            "usr/bin/", "usr/bin/p11-kit",
        ],
        "reason": 0,
        "size": 655360,
    },

    # ---- Crypto / Network layer ----
    # openssl -- PARTIAL UPGRADE  (local 3.2.1-1, sync 3.3.1-1)
    {
        "name": "openssl",
        "local_ver": "3.2.1-1",
        "sync_ver": "3.3.1-1",
        "desc": "The Open Source toolkit for Secure Sockets Layer and Transport Layer Security",
        "url": "https://www.openssl.org",
        "deps": ["glibc"],
        "provides": ["libssl.so=3-64", "libcrypto.so=3-64"],
        "files": [
            "usr/", "usr/bin/", "usr/bin/openssl",
            "usr/lib/", "usr/lib/libssl.so.3", "usr/lib/libcrypto.so.3",
            "etc/", "etc/ssl/", "etc/ssl/openssl.cnf",
        ],
        "reason": 0,
        "size": 11534336,
    },
    # ca-certificates -- FILE CONFLICT
    {
        "name": "ca-certificates",
        "local_ver": "20240618-1",
        "sync_ver": "20240618-1",
        "desc": "Common CA certificates",
        "url": "https://src.fedoraproject.org/rpms/ca-certificates",
        "deps": ["openssl"],
        "provides": [],
        "files": [
            "etc/", "etc/ssl/", "etc/ssl/certs/",
            "etc/ssl/certs/ca-certificates.crt",
            "usr/", "usr/share/", "usr/share/ca-certificates/",
            "usr/share/ca-certificates/mozilla/",
        ],
        "reason": 0,
        "size": 393216,
    },
    # ca-certificates-utils -- FILE CONFLICT
    {
        "name": "ca-certificates-utils",
        "local_ver": "20240618-1",
        "sync_ver": "20240618-1",
        "desc": "Common CA certificates (utilities)",
        "url": "https://src.fedoraproject.org/rpms/ca-certificates",
        "deps": ["openssl", "coreutils"],
        "provides": [],
        "files": [
            "etc/", "etc/ssl/", "etc/ssl/certs/",
            "etc/ssl/certs/ca-certificates.crt",
            "usr/", "usr/bin/", "usr/bin/update-ca-trust",
        ],
        "reason": 0,
        "size": 16384,
    },
    # libnghttp2
    {
        "name": "libnghttp2",
        "local_ver": "1.62.1-1",
        "sync_ver": "1.62.1-1",
        "desc": "Framing layer of HTTP/2 is implemented as a reusable C library",
        "url": "https://nghttp2.org",
        "deps": ["glibc"],
        "provides": ["libnghttp2.so=14-64"],
        "files": ["usr/", "usr/lib/", "usr/lib/libnghttp2.so.14"],
        "reason": 1,
        "size": 196608,
    },
    # libssh2 -- MISSING DEPENDENCY (needs libgcrypt, not installed)
    {
        "name": "libssh2",
        "local_ver": "1.11.0-1",
        "sync_ver": "1.11.0-1",
        "desc": "A library implementing the SSH2 protocol",
        "url": "https://libssh2.org",
        "deps": ["openssl", "zlib", "libgcrypt"],
        "provides": ["libssh2.so=1-64"],
        "files": ["usr/", "usr/lib/", "usr/lib/libssh2.so.1"],
        "reason": 1,
        "size": 262144,
    },
    # curl
    {
        "name": "curl",
        "local_ver": "8.8.0-1",
        "sync_ver": "8.8.0-1",
        "desc": "command line tool and library for transferring data with URLs",
        "url": "https://curl.se",
        "deps": ["openssl>=3.3", "libssh2", "libnghttp2", "zlib", "glibc", "libpsl"],
        "provides": ["libcurl.so=4-64"],
        "files": [
            "usr/", "usr/bin/", "usr/bin/curl",
            "usr/lib/", "usr/lib/libcurl.so.4",
        ],
        "reason": 0,
        "size": 1310720,
    },

    # ---- Python-remnant layer ----
    # libffi
    {
        "name": "libffi",
        "local_ver": "3.4.6-1",
        "sync_ver": "3.4.6-1",
        "desc": "Portable foreign function interface library",
        "url": "https://sourceware.org/libffi",
        "deps": ["glibc"],
        "provides": ["libffi.so=8-64"],
        "files": ["usr/", "usr/lib/", "usr/lib/libffi.so.8"],
        "reason": 0,
        "size": 65536,
    },
    # expat -- CORRUPTED DESC
    {
        "name": "expat",
        "local_ver": "2.6.2-1",
        "sync_ver": "2.6.2-1",
        "desc": "An XML parser library",
        "url": "https://libexpat.github.io/",
        "deps": ["glibc"],
        "provides": ["libexpat.so=1-64"],
        "files": [
            "usr/", "usr/lib/", "usr/lib/libexpat.so.1",
            "usr/bin/", "usr/bin/xmlwf",
        ],
        "reason": 1,
        "size": 283648,
        "corrupted_desc": True,
    },
    # mpdecimal -- ORPHAN
    {
        "name": "mpdecimal",
        "local_ver": "4.0.0-1",
        "sync_ver": "4.0.0-1",
        "desc": "Package for correctly-rounded arbitrary precision decimal floating point arithmetic",
        "url": "https://www.bytereef.org/mpdecimal",
        "deps": ["glibc"],
        "provides": ["libmpdec.so=4-64"],
        "files": ["usr/", "usr/lib/", "usr/lib/libmpdec.so.4"],
        "reason": 1,
        "size": 327680,
    },
    # gdbm -- ORPHAN
    {
        "name": "gdbm",
        "local_ver": "1.23-3",
        "sync_ver": "1.23-3",
        "desc": "GNU database library",
        "url": "https://www.gnu.org/software/gdbm",
        "deps": ["glibc", "readline"],
        "provides": ["libgdbm.so=6-64"],
        "files": ["usr/", "usr/lib/", "usr/lib/libgdbm.so.6"],
        "reason": 1,
        "size": 262144,
    },

    # ---- Misc layer ----
    # sqlite
    {
        "name": "sqlite",
        "local_ver": "3.46.0-1",
        "sync_ver": "3.46.0-1",
        "desc": "A C library that implements an SQL database engine",
        "url": "https://www.sqlite.org",
        "deps": ["glibc", "readline", "zlib", "expat"],
        "provides": ["libsqlite3.so=0-64"],
        "files": [
            "usr/", "usr/bin/", "usr/bin/sqlite3",
            "usr/lib/", "usr/lib/libsqlite3.so.0",
        ],
        "reason": 0,
        "size": 2097152,
    },
    # coreutils
    {
        "name": "coreutils",
        "local_ver": "9.5-1",
        "sync_ver": "9.5-1",
        "desc": "The basic file, shell and text manipulation utilities of the GNU operating system",
        "url": "https://www.gnu.org/software/coreutils",
        "deps": ["glibc", "openssl"],
        "provides": [],
        "files": [
            "usr/", "usr/bin/", "usr/bin/ls", "usr/bin/cp",
            "usr/bin/mv", "usr/bin/rm", "usr/bin/cat", "usr/bin/chmod",
        ],
        "reason": 0,
        "size": 7340032,
    },
    # libidn2
    {
        "name": "libidn2",
        "local_ver": "2.3.7-1",
        "sync_ver": "2.3.7-1",
        "desc": "Free software implementation of IDNA2008, Punycode and TR46",
        "url": "https://www.gnu.org/software/libidn",
        "deps": ["glibc"],
        "provides": ["libidn2.so=0-64"],
        "files": ["usr/", "usr/lib/", "usr/lib/libidn2.so.0"],
        "reason": 1,
        "size": 262144,
    },
    # libpsl
    {
        "name": "libpsl",
        "local_ver": "0.21.5-2",
        "sync_ver": "0.21.5-2",
        "desc": "Public Suffix List library",
        "url": "https://github.com/rockdaboot/libpsl",
        "deps": ["glibc", "libidn2"],
        "provides": ["libpsl.so=5-64"],
        "files": ["usr/", "usr/lib/", "usr/lib/libpsl.so.5"],
        "reason": 1,
        "size": 131072,
    },
    # libgcrypt -- SYNC ONLY (removed from system, needed by libssh2)
    {
        "name": "libgcrypt",
        "local_ver": None,
        "sync_ver": "1.10.3-1",
        "desc": "General purpose cryptographic library based on the code from GnuPG",
        "url": "https://www.gnupg.org",
        "deps": ["glibc"],
        "provides": ["libgcrypt.so=20-64"],
        "files": [
            "usr/", "usr/lib/", "usr/lib/libgcrypt.so.20",
            "usr/bin/", "usr/bin/dumpsexp", "usr/bin/hmac256",
        ],
        "reason": 1,
        "size": 1572864,
    },
]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_local_desc(pkg):
    """Build a pacman local database 'desc' file."""
    packager = pkg.get("packager", "Arch Linux Builder <builder@archlinux.org>")
    sections = [
        "%%NAME%%\n%s" % pkg["name"],
        "%%VERSION%%\n%s" % pkg["local_ver"],
        "%%BASE%%\n%s" % pkg["name"],
        "%%DESC%%\n%s" % pkg["desc"],
        "%%URL%%\n%s" % pkg["url"],
        "%ARCH%\nx86_64",
        "%BUILDDATE%\n1718000000",
        "%INSTALLDATE%\n1718100000",
        "%%PACKAGER%%\n%s" % packager,
        "%%SIZE%%\n%d" % pkg["size"],
        "%%REASON%%\n%d" % pkg["reason"],
        "%VALIDATION%\npgp",
    ]
    if pkg["deps"]:
        sections.append("%%DEPENDS%%\n%s" % "\n".join(pkg["deps"]))
    if pkg.get("provides"):
        sections.append("%%PROVIDES%%\n%s" % "\n".join(pkg["provides"]))
    return "\n\n".join(sections) + "\n\n"


def format_corrupted_desc(pkg):
    """Build a truncated/corrupted desc file for the expat package."""
    return (
        "%%NAME%%\n%s\n\n"
        "%%VERSION%%\n%s\n\n"
        "%%BASE%%\n%s\n\n"
        "%%DESC%%\n%s\n\n"
        "%%URL%%\n%s\n\n"
        "%%ARCH%%\nx86_64\n\n"
        "%%BUILDDATE%%\n1718000000\n\n"
        "%%INSTALLDATE%%\n1718100000\n\n"
        "%%PACKAGER%%\nDavid Runge <dvzrv@archlinux.org>\n\n"
        "%%SIZE%%\n283648\n\n"
        "%%REASON%%\n1\n\n"
        "%%DEPENDS%%\nglib"  # truncated -- should be 'glibc'; no trailing \n
    ) % (pkg["name"], pkg["local_ver"], pkg["name"], pkg["desc"], pkg["url"])


def format_files(file_list):
    """Build a pacman 'files' database entry."""
    return "%%FILES%%\n%s\n\n" % "\n".join(file_list)


def format_sync_desc(pkg):
    """Build a pacman sync database 'desc' file."""
    ver = pkg["sync_ver"]
    packager = pkg.get("packager", "Arch Linux Builder <builder@archlinux.org>")
    sections = [
        "%%FILENAME%%\n%s-%s-x86_64.pkg.tar.zst" % (pkg["name"], ver),
        "%%NAME%%\n%s" % pkg["name"],
        "%%BASE%%\n%s" % pkg["name"],
        "%%VERSION%%\n%s" % ver,
        "%%DESC%%\n%s" % pkg["desc"],
        "%%CSIZE%%\n%d" % (pkg["size"] // 3),
        "%%ISIZE%%\n%d" % pkg["size"],
        "%%SHA256SUM%%\n%s" % ("a" * 64),
        "%%URL%%\n%s" % pkg["url"],
        "%ARCH%\nx86_64",
        "%BUILDDATE%\n1718000000",
        "%%PACKAGER%%\n%s" % packager,
    ]
    if pkg["deps"]:
        sections.append("%%DEPENDS%%\n%s" % "\n".join(pkg["deps"]))
    if pkg.get("provides"):
        sections.append("%%PROVIDES%%\n%s" % "\n".join(pkg["provides"]))
    return "\n\n".join(sections) + "\n\n"


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

PACMAN_LOG = """\
[2024-05-15T12:00:00+0000] [PACMAN] Running 'pacman -Syu'
[2024-05-15T12:00:02+0000] [PACMAN] synchronizing package lists
[2024-05-15T12:00:05+0000] [ALPM] transaction started
[2024-05-15T12:00:06+0000] [ALPM] upgraded linux-api-headers (6.7-1 -> 6.8-1)
[2024-05-15T12:00:07+0000] [ALPM] upgraded glibc (2.38-7 -> 2.39-1)
[2024-05-15T12:00:08+0000] [ALPM] upgraded gcc-libs (13.2.1-6 -> 14.1.1-1)
[2024-05-15T12:00:09+0000] [ALPM] upgraded ncurses (6.2-2 -> 6.3-1)
[2024-05-15T12:00:10+0000] [ALPM] upgraded readline (8.2.007-1 -> 8.2.010-1)
[2024-05-15T12:00:11+0000] [ALPM] upgraded openssl (3.1.4-1 -> 3.2.1-1)
[2024-05-15T12:00:12+0000] [ALPM] upgraded bash (5.2.021-2 -> 5.2.026-1)
[2024-05-15T12:00:13+0000] [ALPM] upgraded curl (8.7.1-4 -> 8.8.0-1)
[2024-05-15T12:00:14+0000] [ALPM] upgraded icu (1:73.2-2 -> 1:74.2-1)
[2024-05-15T12:00:15+0000] [ALPM] upgraded libxml2 (2.12.6-1 -> 2.12.7-1)
[2024-05-15T12:00:30+0000] [ALPM] transaction completed
[2024-06-01T09:00:00+0000] [PACMAN] Running 'pacman -R python'
[2024-06-01T09:00:01+0000] [ALPM] transaction started
[2024-06-01T09:00:01+0000] [ALPM] removed python (3.12.3-1)
[2024-06-01T09:00:02+0000] [ALPM] transaction completed
[2024-06-05T14:00:00+0000] [PACMAN] Running 'pacman -Rdd libgcrypt'
[2024-06-05T14:00:01+0000] [ALPM] transaction started
[2024-06-05T14:00:01+0000] [ALPM] removed libgcrypt (1.10.3-1)
[2024-06-05T14:00:02+0000] [ALPM] transaction completed
[2024-06-10T08:00:00+0000] [PACMAN] Running 'pacman -Sy'
[2024-06-10T08:00:02+0000] [PACMAN] synchronizing package lists
[2024-06-10T08:00:03+0000] [ALPM] warning: icu: local (1:74.2-1) is older than core (1:75.1-1)
[2024-06-10T08:15:00+0000] [PACMAN] Running 'pacman -Sdd bash curl'
[2024-06-10T08:15:01+0000] [ALPM] warning: skipping dependency version checks
[2024-06-10T08:15:02+0000] [ALPM] transaction started
[2024-06-10T08:15:03+0000] [ALPM] upgraded bash (5.2.021-2 -> 5.2.026-1)
[2024-06-10T08:15:04+0000] [ALPM] upgraded curl (8.7.1-4 -> 8.8.0-1)
[2024-06-10T08:15:05+0000] [ALPM] transaction completed
[2024-06-10T08:45:00+0000] [PACMAN] Running 'pacman -S --overwrite "*" ca-certificates-utils'
[2024-06-10T08:45:01+0000] [ALPM] transaction started
[2024-06-10T08:45:02+0000] [ALPM] installed ca-certificates-utils (20240618-1)
[2024-06-10T08:45:03+0000] [ALPM] warning: /etc/ssl/certs/ca-certificates.crt exists in filesystem (owned by ca-certificates)
[2024-06-10T08:45:04+0000] [ALPM] transaction completed
[2024-06-10T09:00:00+0000] [ALPM] warning: I/O error during database sync
[2024-06-10T09:00:01+0000] [ALPM] warning: file /var/lib/pacman/local/readline-8.2.010-1/desc: unexpected end of file
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Create directory structure
    os.makedirs(LOCAL_DB, exist_ok=True)
    os.makedirs(SYNC_DIR, exist_ok=True)
    os.makedirs(os.path.join(ARCHROOT, "var/cache/pacman/pkg"), exist_ok=True)
    os.makedirs(os.path.join(ARCHROOT, "var/log"), exist_ok=True)

    # ALPM database version
    with open(os.path.join(LOCAL_DB, "ALPM_DB_VERSION"), "w") as f:
        f.write("9\n")

    for pkg in PACKAGES:
        # ---- Local database ----
        if pkg.get("local_ver"):
            pkg_dir_name = "%s-%s" % (pkg["name"], pkg["local_ver"])
            pkg_dir = os.path.join(LOCAL_DB, pkg_dir_name)
            os.makedirs(pkg_dir, exist_ok=True)

            # Write desc (unless missing_desc flag)
            if not pkg.get("missing_desc"):
                if pkg.get("corrupted_desc"):
                    desc_content = format_corrupted_desc(pkg)
                else:
                    desc_content = format_local_desc(pkg)
                with open(os.path.join(pkg_dir, "desc"), "w") as f:
                    f.write(desc_content)

            # Write files
            with open(os.path.join(pkg_dir, "files"), "w") as f:
                f.write(format_files(pkg["files"]))

    # ---- Sync database as tar.zst archive ----
    tar_path = os.path.join(SYNC_DIR, "core.tar")
    with tarfile.open(tar_path, "w") as tar:
        for pkg in PACKAGES:
            desc_content = format_sync_desc(pkg)
            content_bytes = desc_content.encode("utf-8")
            sync_dir_name = "%s-%s" % (pkg["name"], pkg["sync_ver"])

            # Add directory entry
            dir_info = tarfile.TarInfo(name=sync_dir_name + "/")
            dir_info.type = tarfile.DIRTYPE
            dir_info.mode = 0o755
            tar.addfile(dir_info)

            # Add desc file
            desc_info = tarfile.TarInfo(name=sync_dir_name + "/desc")
            desc_info.size = len(content_bytes)
            desc_info.mode = 0o644
            tar.addfile(desc_info, io.BytesIO(content_bytes))

    # Compress with zstd
    db_path = os.path.join(SYNC_DIR, "core.db")
    subprocess.run(["zstd", "-q", "-o", db_path, tar_path], check=True)
    os.remove(tar_path)

    # ---- SQLite package metadata cache ----
    meta_db_path = os.path.join(ARCHROOT, "var/lib/pacman/package_metadata.db")
    conn = sqlite3.connect(meta_db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE package_sizes (
        name TEXT PRIMARY KEY,
        compressed_size INTEGER,
        installed_size INTEGER,
        repository TEXT DEFAULT 'core'
    )""")
    for pkg in PACKAGES:
        c.execute("INSERT INTO package_sizes VALUES (?, ?, ?, ?)",
                  (pkg["name"], pkg["size"] // 3, pkg["size"], "core"))

    c.execute("""CREATE TABLE repo_state (
        repository TEXT PRIMARY KEY,
        last_sync_timestamp TEXT,
        total_packages INTEGER,
        mirror_url TEXT
    )""")
    c.execute("INSERT INTO repo_state VALUES (?, ?, ?, ?)",
              ("core", "2024-06-10T08:00:00+0000", len(PACKAGES),
               "https://mirrors.kernel.org/archlinux/core/os/x86_64"))

    conn.commit()
    conn.close()

    # Write pacman log
    with open(os.path.join(ARCHROOT, "var/log/pacman.log"), "w") as f:
        f.write(PACMAN_LOG)

    local_count = sum(1 for p in PACKAGES if p.get("local_ver"))
    print("Database generated at %s" % ARCHROOT)
    print("  Local packages: %d" % local_count)
    print("  Sync packages:  %d (in core.db tar.zst)" % len(PACKAGES))
    print("  Metadata DB:    %s" % meta_db_path)


if __name__ == "__main__":
    main()
