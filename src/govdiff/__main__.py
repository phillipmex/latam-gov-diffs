"""Allow `python -m govdiff`."""

from govdiff.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
