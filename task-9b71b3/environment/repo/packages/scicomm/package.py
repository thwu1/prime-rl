# Copyright Scistack Project Developers.
# SPDX-License-Identifier: MIT

from spack.package import *


class Scicomm(Package):
    """Standard scientific communication library implementing the scimpi
    message-passing interface up to version 2.0 of the specification."""

    homepage = "https://example.com/scicomm"
    url = "https://example.com/scicomm-4.0.0.tar.gz"

    version("4.1.0", sha256="d6e5b1f24c7a3098e1d5c6b7a8e9f0d1c2b3a4f5e6d7c8b9a0f1e2d3c4b5a6e7")
    version("4.0.0", sha256="e7f6c2a35d8b4109f2e6d7c8b9f0a1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6b7a8")
    version("3.0.0", sha256="f8a7d3b46e9c5210a3f7e8d9c0a1b2f3e4d5c6b7a8f9e0d1c2b3a4f5e6d7c8b9")

    variant("threads", default=False, description="Enable multi-threading support")

    provides("scimpi@:2.0")

    depends_on("scibase@1.2:")

    def install(self, spec, prefix):
        mkdirp(prefix.lib)
        mkdirp(prefix.include)
