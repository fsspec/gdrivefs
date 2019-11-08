import os

import gdrivefs
import pytest

testdir = "testdir"


@pytest.fixture()
def creds():
    tfile = "tfile.pickle" if os.environ.get("TRAVIS", "") else None
    fs = gdrivefs.GoogleDriveFileSystem(token='cache', tokens_file=tfile)
    if fs.exists(testdir):
        fs.rm(testdir, recursive=True)
    fs.mkdir(testdir)
    try:
        yield tfile
    finally:
        try:
            fs.rm(testdir, recursive=True)
        except IOError:
            pass


def test_simple(creds):
    fs = gdrivefs.GoogleDriveFileSystem(token='cache', tokens_file=creds)
    assert fs.ls("")
    data = b'hello'
    fn = testdir + "/testfile"
    with fs.open(fn, 'wb') as f:
        f.write(data)
    assert fs.cat(fn) == data
