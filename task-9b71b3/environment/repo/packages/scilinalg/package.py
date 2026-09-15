# Copyright Scistack Project Developers.
# SPDX-License-Identifier: MIT

from spack.package import *


class Scilinalg(Package):
    """Scientific linear algebra library providing dense and sparse solver
    routines for HPC workloads."""

    homepage = "https://example.com/scilinalg"
    url = "https://example.com/scilinalg-2.5.0.tar.gz"

    version("2.5.0", sha256="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2")
    version("2.3.0", sha256="b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3")

    variant("shared", default=True, description="Build shared libraries")

    depends_on("scibase@1.2:")

    conflicts("%gcc@13:", msg="Requires GCC 12.x or earlier due to Fortran ABI changes")

    def install(self, spec, prefix):
        mkdirp(prefix.lib)
        mkdirp(prefix.include)
