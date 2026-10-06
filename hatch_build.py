"""Refuse to build a wheel without the page scripts.

native/amberfader/embedded/web/ is a build output (npm run build), ignored by
git, so hatch only ships it because pyproject.toml declares it an artifact.
A wheel built before `npm run build` would install an app that cannot start;
fail the build instead. Editable installs (uv sync) are exempt: they read the
files from the checkout at run time.
"""
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

PAGE_SCRIPTS = ("adapter.js", "ad-filter.js")


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        if version == "editable":
            return
        web = Path(self.root) / "native" / "amberfader" / "embedded" / "web"
        missing = [name for name in PAGE_SCRIPTS if not (web / name).is_file()]
        if missing:
            raise RuntimeError(
                f"page scripts missing from {web}: {', '.join(missing)}. "
                "Run `npm ci && npm run build` first."
            )
