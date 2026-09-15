# Copyright Scistack Project Developers.
# SPDX-License-Identifier: MIT

from spack.package import *


class Scifft(Package):
    """Fast Fourier Transform library for scientific computing with support
    for multi-dimensional transforms and distributed computation."""

    homepage = "https://example.com/scifft"
    url = "https://example.com/scifft-3.0.0.tar.gz"

    version("3.3.10", sha256="a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8")
    version("3.3.8", sha256="b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9")

    variant("mpi", default=False, description="Enable distributed FFT via scimpi")
    variant(
        "precision",
        default="double",
        values=("single", "double", "quad"),
        description="Floating point precision",
    )

    depends_on("scibase")
    depends_on("scimpi", when="+mpi")

    def install(self, spec, prefix):
        mkdirp(prefix.lib)
        mkdirp(prefix.include)
