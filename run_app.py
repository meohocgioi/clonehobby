"""Entry point for the packaged app (double-click): runs the dashboard and opens the browser."""
import sys

from tpclone.cli import main

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv += ["run", "--open"]
    main()
