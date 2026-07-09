"""Allow ``python -m djlego.ui`` as an alternative launch path."""

from ..app import main

if __name__ == "__main__":
    raise SystemExit(main())
