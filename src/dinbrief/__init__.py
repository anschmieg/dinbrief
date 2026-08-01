"""dinbrief package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("dinbrief")
except PackageNotFoundError:  # pragma: no cover - only possible in an unpackaged source tree
    __version__ = "0+unknown"
