#!/usr/bin/env python
import os

from setuptools import setup
import versioneer

here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    name="gdrivefs",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    description="File system on GDrive",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="http://github.com/fsspec/gdrivefs",
    maintainer="Martin Durant",
    maintainer_email="mdurant@anaconda.com",
    license="BSD",
    keywords="file",
    packages=["gdrivefs", "gdrivefs.tests"],
    python_requires=">=3.7",
    install_requires=open("requirements.txt").read().strip().split("\n"),
    zip_safe=False,
)
