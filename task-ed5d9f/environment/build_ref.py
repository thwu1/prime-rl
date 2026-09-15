from setuptools import setup, Extension
from Cython.Build import cythonize

setup(
    ext_modules=cythonize(
        [Extension("block_manager_ref", ["block_manager_ref.py"])],
        compiler_directives={"language_level": "3"},
    ),
    script_args=["build_ext", "--inplace"],
)
