#!/usr/bin/env python
import os

from setuptools import setup
import versioneer

here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="gdrivefs",
    version="0.0.1",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
    ],
    description="Frile system on GDrive",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="http://github.com/tbd",
    maintainer="Martin Durant",
    maintainer_email="mdurant@anaconda.com",
    license="BSD",
    keywords="file",
    packages=["gdrivefs", "gdrivefs.tests"],
    python_requires=">3.5",
    install_requires=open("requirements.txt").read().strip().split("\n"),
    zip_safe=False,
)
