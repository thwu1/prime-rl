# Copyright Scistack Project Developers.
# SPDX-License-Identifier: MIT

from spack.package import *


class Scibase(Package):
    """Foundational scientific computing base library providing core data
    structures and utility routines used across the scistack ecosystem."""

    homepage = "https://example.com/scibase"
    url = "https://example.com/scibase-1.0.0.tar.gz"

    version("1.3.0", sha256="a3f2b8c91d4e0765f8a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4")
    version("1.2.0", sha256="b4e3c9d02a5f1876e9b3c4d5a6f7e8b9c0d1a2f3e4b5c6d7a8f9e0b1c2d3a4f5")
    version("1.0.0", sha256="c5d4a0e13b6f2987d0c4b5e6a7f8d9c0b1e2a3f4d5c6b7a8e9f0d1c2b3a4e5f6")

    variant("shared", default=True, description="Build shared libraries")
    variant("pic", default=True, description="Position independent code")

    def install(self, spec, prefix):
        mkdirp(prefix.lib)
        mkdirp(prefix.include)
