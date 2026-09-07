"""Exception types shared across govdiff."""


class GovDiffError(Exception):
    """Base class for every error this package raises deliberately."""


class SourceChallenged(GovDiffError):
    """The publisher answered with an anti-bot wall.

    Raised on 403/429/503 or on a body that carries challenge/captcha markers.
    The run for that feed stops here. There is no bypass path by design: a
    challenged source is a dead source until the publisher changes its mind.
    """


class SourceTooLarge(GovDiffError):
    """The response exceeded the configured hard byte ceiling."""


class FeedError(GovDiffError):
    """A feed is misconfigured, or its parser could not make sense of the file."""


class RepoNotFound(GovDiffError):
    """No archive checkout could be resolved.

    Raised when `--repo` was not given, `GOVDIFF_REPO` is unset or wrong, and
    the working directory is not an archive checkout. The message tells the
    reader how to fix it; see `config.resolve_repo_root`.
    """
