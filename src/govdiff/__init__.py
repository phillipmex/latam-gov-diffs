"""govdiff - snapshot and diff Latin American government reference data."""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    # pyproject.toml is the single source of truth for the version. A second
    # copy here would drift, and `govdiff --version` reporting a number that is
    # not the number PyPI shipped is exactly the kind of quiet lie this project
    # is meant to be the opposite of.
    __version__ = _version("govdiff")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0.0.0+source"

from govdiff.errors import GovDiffError, SourceChallenged, SourceTooLarge, FeedError

__all__ = ["GovDiffError", "SourceChallenged", "SourceTooLarge", "FeedError", "__version__"]
