# Copyright Scistack Project Developers.
# SPDX-License-Identifier: MIT

from spack.package import *


class Scimath(Package):
    """Scientific mathematics library providing BLAS, LAPACK, and sparse
    linear algebra routines optimized for HPC workloads."""

    homepage = "https://example.com/scimath"
    url = "https://example.com/scimath-3.0.0.tar.gz"

    version("3.3.0", sha256="c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4")
    version("3.2.0", sha256="d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5")

    variant("mpi", default=False, description="Enable distributed linear algebra via scimpi")
    variant(
        "precision",
        default="double",
        values=("single", "double", "quad"),
        description="Floating point precision",
    )

    depends_on("scibase@1.2:")
    depends_on("scimpi", when="+mpi")

    def install(self, spec, prefix):
        mkdirp(prefix.lib)
        mkdirp(prefix.include)
