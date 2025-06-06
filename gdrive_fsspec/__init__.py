try:
    from ._version import version as __version__
except ImportError:
    __version__ = "0.dev"

from .core import GoogleDriveFileSystem

__all__ = ["GoogleDriveFileSystem"]
