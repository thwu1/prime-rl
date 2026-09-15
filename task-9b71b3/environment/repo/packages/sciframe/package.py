# Copyright Scistack Project Developers.
# SPDX-License-Identifier: MIT

from spack.package import *


class Sciframe(Package):
    """Comprehensive scientific computing framework integrating linear algebra,
    FFT, and parallel I/O for large-scale simulation and data analysis
    workflows on HPC systems."""

    homepage = "https://example.com/sciframe"
    url = "https://example.com/sciframe-3.0.0.tar.gz"

    version("3.20.0", sha256="c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0")
    version("3.18.0", sha256="d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1")

    variant("parallel", default=True, description="Enable distributed computing via scimpi")
    variant("io", default=True, description="Enable high-performance I/O")
    variant("debug", default=False, description="Build with debug symbols")

    depends_on("scibase@1.2:")
    depends_on("sci-math")
    depends_on("scimpi@3:", when="+parallel")
    depends_on("sciio+parallel", when="+io")
    depends_on("scifft+mpi", when="+parallel")

    def install(self, spec, prefix):
        mkdirp(prefix.lib)
        mkdirp(prefix.include)
