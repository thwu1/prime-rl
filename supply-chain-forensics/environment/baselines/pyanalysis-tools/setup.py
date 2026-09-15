from setuptools import setup, find_packages
from setuptools.command.install import install
import sys
import os

class CustomInstall(install):
    """Custom installer that shows a welcome banner after installation."""
    def run(self):
        install.run(self)
        self._post_install()

    def _post_install(self):
        import base64
        # Display ASCII welcome banner
        banner = base64.b64decode(
            "V2VsY29tZSB0byBweWFuYWx5c2lzLXRvb2xzIHYxLjAuMCE="
        ).decode()
        print(banner)
        print("Documentation: https://pyanalysis-tools.readthedocs.io")
        print("Report issues: https://github.com/analytics-collective/pyanalysis-tools/issues")

setup(
    name='pyanalysis-tools',
    version='1.0.0',
    author='analytics-collective',
    author_email='analytics@example.com',
    description='Statistical analysis and data processing utilities for Python',
    long_description=open('README.md').read() if os.path.exists('README.md') else '',
    long_description_content_type='text/markdown',
    url='https://github.com/analytics-collective/pyanalysis-tools',
    packages=find_packages(),
    python_requires='>=3.8',
    install_requires=[
        'numpy>=1.20.0',
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
    ],
    cmdclass={'install': CustomInstall},
)
