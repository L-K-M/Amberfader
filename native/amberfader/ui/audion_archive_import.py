"""Install every face of an Audion collection ZIP, with progress and Stop."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QProgressDialog, QWidget

from ..audion_import import AudionArchive, AudionInstallOutcome, AudionInstallStatus
from ..face_library import FaceLibrary
from .face_surface import prepare_face


@dataclass(frozen=True)
class AudionArchiveImport:
    outcomes: tuple[AudionInstallOutcome, ...]
    total: int  # Faces in the archive; more than the outcomes if stopped.

    @property
    def installed(self) -> tuple[AudionInstallOutcome, ...]:
        return tuple(
            outcome for outcome in self.outcomes
            if outcome.status is AudionInstallStatus.INSTALLED
        )

    def summary(self) -> tuple[str, str]:
        """A short report and the per-face failure details."""
        counts = Counter(outcome.status for outcome in self.outcomes)
        installed = counts[AudionInstallStatus.INSTALLED]
        lines = [f"Installed {installed} of {self.total} Audion faces."]
        if len(self.outcomes) < self.total:
            lines.append("Import stopped. Faces installed before stopping stay installed.")
        if counts[AudionInstallStatus.ALREADY_INSTALLED]:
            lines.append(
                f"{counts[AudionInstallStatus.ALREADY_INSTALLED]} were already installed."
            )
        if counts[AudionInstallStatus.FAILED]:
            lines.append(
                f"{counts[AudionInstallStatus.FAILED]} could not be imported. See the details."
            )
        if installed:
            lines.append("Double-click a face under Installed to edit it.")
        details = "\n".join(
            f"{outcome.face.name}: {outcome.problem}" for outcome in self.outcomes
            if outcome.status is AudionInstallStatus.FAILED
        )
        return "\n".join(lines), details


def import_audion_archive(
    path: Path, library: FaceLibrary, parent: QWidget,
) -> AudionArchiveImport:
    """Install the faces one by one; Stop keeps those already installed.

    Raises FaceError when the archive cannot be read.
    """
    library.refresh()  # Skip faces installed since the library last looked.
    with AudionArchive(path) as archive:
        faces = archive.faces
        progress = QProgressDialog("Importing Audion faces…", "Stop", 0, len(faces), parent)
        progress.setWindowTitle("Import Audion faces")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        outcomes = []
        # setValue() alone would show the dialog only after the first face.
        progress.show()
        try:
            for index, face in enumerate(faces):
                progress.setLabelText(f"Importing {face.name}…")
                progress.setValue(index)
                # Paint the face about to block and deliver Stop clicks.
                QApplication.processEvents()
                if progress.wasCanceled():
                    break
                outcomes.append(archive.install(face, library, prepare_face))
            progress.setValue(len(faces))
        finally:
            progress.close()
            progress.deleteLater()
    return AudionArchiveImport(tuple(outcomes), len(faces))
