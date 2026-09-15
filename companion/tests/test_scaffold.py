"""Sanity check that the companion package and pytest are wired up correctly."""

import companion


def test_package_imports() -> None:
    assert companion is not None
