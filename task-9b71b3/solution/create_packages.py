#!/usr/bin/env python3
"""
Build the SciStack package ecosystem for Spack.

Analyzes the requirements at /app/requirements.md, creates missing packages
(scicomm-ng, scifft, scisolver), completes the incomplete scilinalg package
(adds mpi/precision variants, removes invalid gcc@13 conflict), and configures
the Spack environment for unified concretization.

Key design decisions:
- scicomm-ng provides scimpi@3.1 because scisolver requires scimpi@3: and the
  existing scicomm only provides scimpi@:2.0
- scilinalg's conflicts("%gcc@13:") must be removed since Ubuntu 24.04 only
  ships gcc 13.x — keeping it makes concretization unsatisfiable
- scisolver propagates +mpi and precision=double to scilinalg and scifft via
  conditional depends_on directives
"""

import os

REPO_PACKAGES = "/app/repo/packages"
ENV_DIR = "/app/env"


def write_package(pkg_name, content):
    """Write a Spack package.py file to the repository."""
    pkg_dir = os.path.join(REPO_PACKAGES, pkg_name)
    os.makedirs(pkg_dir, exist_ok=True)
    pkg_path = os.path.join(pkg_dir, "package.py")
    with open(pkg_path, "w") as f:
        f.write(content)
    print(f"Created {pkg_path}")


# ---------------------------------------------------------------------------
# scicomm-ng: new provider for scimpi@3.1
# ---------------------------------------------------------------------------
# The existing scicomm only provides scimpi@:2.0. The scisolver package needs
# scimpi@3: for its MPI path, so we must create a provider that satisfies this.
# scicomm-ng provides scimpi@3.1 and depends on scibase@1.2: for compatibility
# with the rest of the ecosystem.

write_package("scicomm-ng", """\
# Copyright Scistack Project Developers.
# SPDX-License-Identifier: MIT

from spack.package import *


class ScicommNg(Package):
    \"\"\"Next-generation scientific communication library implementing
    version 3.1 of the scimpi message-passing specification with
    advanced collective operations.\"\"\"

    homepage = "https://example.com/scicomm-ng"
    url = "https://example.com/scicomm-ng-2.1.0.tar.gz"

    version("2.1.0", sha256="c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4")
    version("2.0.0", sha256="d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5")

    variant("threads", default=False, description="Enable multi-threading support")

    provides("scimpi@3.1")

    depends_on("scibase@1.2:")

    def install(self, spec, prefix):
        mkdirp(prefix.lib)
        mkdirp(prefix.include)
""")


# ---------------------------------------------------------------------------
# scifft: FFT library with MPI and precision support
# ---------------------------------------------------------------------------
# Supports distributed FFT via conditional scimpi dependency when +mpi,
# and configurable floating-point precision.

write_package("scifft", """\
# Copyright Scistack Project Developers.
# SPDX-License-Identifier: MIT

from spack.package import *


class Scifft(Package):
    \"\"\"FFT library for scientific computing supporting multi-dimensional
    transforms with distributed computation via MPI.\"\"\"

    homepage = "https://example.com/scifft"
    url = "https://example.com/scifft-3.3.10.tar.gz"

    version("3.3.10", sha256="e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6")
    version("3.3.8", sha256="f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7")

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
""")


# ---------------------------------------------------------------------------
# scisolver: PDE solver framework
# ---------------------------------------------------------------------------
# Top-level package. When +mpi, pulls in MPI-enabled linalg and FFT with
# double precision, and requires scimpi@3: (only satisfiable by scicomm-ng).
# When ~mpi, still requires double precision but no MPI dependencies.

write_package("scisolver", """\
# Copyright Scistack Project Developers.
# SPDX-License-Identifier: MIT

from spack.package import *


class Scisolver(Package):
    \"\"\"PDE solver framework for large-scale scientific simulations
    with support for distributed-memory parallelism.\"\"\"

    homepage = "https://example.com/scisolver"
    url = "https://example.com/scisolver-5.2.0.tar.gz"

    version("5.2.0", sha256="a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8")
    version("5.0.0", sha256="b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9")

    variant("mpi", default=True, description="Enable distributed-memory parallelism")
    variant("debug", default=False, description="Build with debug symbols")

    depends_on("scibase@1.2:")
    depends_on("scilinalg+mpi precision=double", when="+mpi")
    depends_on("scilinalg precision=double", when="~mpi")
    depends_on("scifft+mpi precision=double", when="+mpi")
    depends_on("scifft precision=double", when="~mpi")
    depends_on("scimpi@3:", when="+mpi")

    def install(self, spec, prefix):
        mkdirp(prefix.lib)
        mkdirp(prefix.include)
""")


# ---------------------------------------------------------------------------
# scilinalg: fix incomplete package
# ---------------------------------------------------------------------------
# The existing scilinalg is missing:
#   1. mpi variant with conditional scimpi dependency
#   2. precision variant (single/double/quad)
# And has an invalid constraint:
#   3. conflicts("%gcc@13:") — impossible on Ubuntu 24.04 which only has gcc 13.x
#
# We rewrite the package with the missing features added and the conflict removed.

write_package("scilinalg", """\
# Copyright Scistack Project Developers.
# SPDX-License-Identifier: MIT

from spack.package import *


class Scilinalg(Package):
    \"\"\"Scientific linear algebra library providing dense and sparse solver
    routines for HPC workloads.\"\"\"

    homepage = "https://example.com/scilinalg"
    url = "https://example.com/scilinalg-2.5.0.tar.gz"

    version("2.5.0", sha256="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2")
    version("2.3.0", sha256="b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3")

    variant("shared", default=True, description="Build shared libraries")
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
""")


# ---------------------------------------------------------------------------
# Create environment configuration
# ---------------------------------------------------------------------------
os.makedirs(ENV_DIR, exist_ok=True)
env_path = os.path.join(ENV_DIR, "spack.yaml")
with open(env_path, "w") as f:
    f.write("""\
spack:
  repos:
    - /app/repo
  specs:
    - scisolver +mpi
    - scifft +mpi precision=double
  concretizer:
    unify: true
""")
print(f"Created {env_path}")
