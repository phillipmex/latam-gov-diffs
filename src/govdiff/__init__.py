"""govdiff - snapshot and diff Latin American government reference data."""

__version__ = "0.1.0"

from govdiff.errors import GovDiffError, SourceChallenged, SourceTooLarge, FeedError

__all__ = ["GovDiffError", "SourceChallenged", "SourceTooLarge", "FeedError", "__version__"]
