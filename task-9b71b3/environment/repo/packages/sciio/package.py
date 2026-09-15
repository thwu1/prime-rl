# Copyright Scistack Project Developers.
# SPDX-License-Identifier: MIT

from spack.package import *


class Sciio(Package):
    """High-performance scientific I/O library supporting parallel file
    access patterns for large-scale simulation data."""

    homepage = "https://example.com/sciio"
    url = "https://example.com/sciio-1.0.0.tar.gz"

    version("1.14.0", sha256="e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6")
    version("1.12.0", sha256="f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7")

    variant("parallel", default=False, description="Enable parallel I/O via scimpi")
    variant("shared", default=True, description="Build shared libraries")

    depends_on("scibase@1.2:")
    depends_on("scimpi", when="+parallel")

    conflicts("%gcc@13:", msg="Package requires GCC 12.x or earlier due to Fortran ABI changes")

    def install(self, spec, prefix):
        mkdirp(prefix.lib)
        mkdirp(prefix.include)
