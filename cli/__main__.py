"""Entry point for ``python -m cli``: delegate to the Typer app defined in the package.

Kept thin (the commands live in ``cli/__init__.py``) so the package can also be imported — by
tests, for instance — without the main module being executed twice.
"""

from cli import app

if __name__ == "__main__":
    app()
