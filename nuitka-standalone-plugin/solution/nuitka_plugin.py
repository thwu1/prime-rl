"""Nuitka user plugin for the text processing pipeline.

Resolves three categories of standalone compilation issues:
1. Dynamic imports - backends discovered via pkgutil/importlib at runtime
2. Data files - templates loaded via __file__-relative paths
3. Native library - C shared library loaded via ctypes

"""
import os

from nuitka.plugins.PluginBase import NuitkaPluginBase


class TextPipelinePlugin(NuitkaPluginBase):
    plugin_name = "text-pipeline"
    plugin_desc = "Handle standalone issues for the text processing pipeline"

    @staticmethod
    def isAlwaysEnabled():
        return True

    def getImplicitImports(self, module):
        full_name = module.getFullName()
        if full_name == "__main__":
            yield "backends"
            yield "backends.text_reverse"
            yield "backends.text_cipher"
            yield "backends.text_stats"
            yield "backends.text_hash"

    def considerDataFiles(self, module):
        full_name = module.getFullName()
        if full_name == "__main__":
            app_dir = os.path.dirname(module.getCompileTimeFilename())
            # Bundle template data files
            for fname in ("header.txt", "footer.txt"):
                source = os.path.join(app_dir, "data", fname)
                yield self.makeIncludedDataFile(
                    source_path=source,
                    dest_path=os.path.join("data", fname),
                    reason="Template file for text processing pipeline",
                )
            # Bundle native C shared library preserving directory structure
            # so that the __file__-relative ctypes.CDLL path in text_hash resolves
            lib_source = os.path.join(app_dir, "native", "libhashutil.so")
            yield self.makeIncludedDataFile(
                source_path=lib_source,
                dest_path=os.path.join("native", "libhashutil.so"),
                reason="Native hash library for text_hash backend",
            )
