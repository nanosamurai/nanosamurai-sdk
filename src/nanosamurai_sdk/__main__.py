"""Module entrypoint.

Allows running the CLI via:

  py -m nanosamurai_sdk ...
"""

from __future__ import annotations

from .cli import main


if __name__ == "__main__":
    main()
