"""Hand files to the desktop: reveal a folder in Finder or the file manager.

Qt-free so the UI never starts processes itself.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

OPEN_COMMAND = "/usr/bin/open"


def reveal(path: Path) -> bool:
    """Show `path` selected in Finder; elsewhere open its parent folder.

    Returns False when the file manager could not be started.
    """
    path = Path(path)
    if sys.platform == "darwin":
        command = [OPEN_COMMAND, "-R", str(path)]
    else:
        command = ["xdg-open", str(path.parent)]
    try:
        subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError:
        return False
    return True
