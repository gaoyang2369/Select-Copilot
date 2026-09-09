"""Build a windowed portable folder and zip; never copy local credentials."""

from __future__ import annotations

from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if sys.platform != "win32" or platform.machine().upper() not in ("AMD64", "X86_64") or struct.calcsize("P") != 8:
        raise SystemExit("Build this application with x64 Python on Windows x64.")
    sys.path.insert(0, str(ROOT))
    from PySide6.QtWidgets import QApplication
    from ui.tray import CopilotTray

    (ROOT / "build").mkdir(exist_ok=True)
    application = QApplication([])
    tray = CopilotTray(lambda: None, lambda _: None, lambda: None)
    if not tray.icon().pixmap(64, 64).save(str(ROOT / "build" / "app.ico"), "ICO"):
        raise RuntimeError("Could not generate the Windows icon.")

    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    str(ROOT / "SelectionCopilot.spec")], cwd=ROOT, check=True)
    folder = ROOT / "dist" / "SelectionCopilot"
    # Only these public documents are copied beside the executable.
    shutil.copyfile(ROOT / ".env.example", folder / ".env.example")
    shutil.copyfile(ROOT / "docs" / "Windows使用说明.txt", folder / "使用说明.txt")
    forbidden = {".env", "settings.json", "app.log"}
    if any(path.name in forbidden for path in folder.rglob("*")):
        raise RuntimeError("Unexpected local configuration found in the distribution.")
    archive = shutil.make_archive(str(ROOT / "dist" / "SelectionCopilot-win64"), "zip",
                                  root_dir=ROOT / "dist", base_dir="SelectionCopilot")
    print(f"Executable: {folder / 'SelectionCopilot.exe'}")
    print(f"Archive: {archive}")


if __name__ == "__main__":
    main()
