# Copyright Scistack Project Developers.
# SPDX-License-Identifier: MIT

from spack.package import *


class ScicommAlt(Package):
    """Alternative high-performance implementation of the scimpi message-passing
    interface supporting version 3.1 of the specification with advanced
    collective operations and GPU-aware communication."""

    homepage = "https://example.com/scicomm-alt"
    url = "https://example.com/scicomm-alt-2.0.0.tar.gz"

    version("2.1.0", sha256="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2")
    version("2.0.0", sha256="b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3")

    provides("scimpi@3.1")

    depends_on("scibase@:0.9")

    def install(self, spec, prefix):
        mkdirp(prefix.lib)
        mkdirp(prefix.include)
