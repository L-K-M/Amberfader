"""Fresh package installs must retain WebEngine and macOS 13 support."""
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]
BUNDLED_WEBENGINE_VERSION = "6.11.2"
SPLIT_WEBENGINE_VERSION = "6.12.0"


@pytest.mark.parametrize("package", ["pyside6-addons", "pyside6-essentials"])
def test_qt_dependencies_exclude_the_split_webengine_release(package):
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    requirements = [Requirement(value) for value in metadata["project"]["dependencies"]]
    specifier = next(
        requirement.specifier for requirement in requirements
        if canonicalize_name(requirement.name) == package
    )

    # 6.12 removes WebEngine from Addons and its macOS wheels require 14.
    assert BUNDLED_WEBENGINE_VERSION in specifier
    assert SPLIT_WEBENGINE_VERSION not in specifier
