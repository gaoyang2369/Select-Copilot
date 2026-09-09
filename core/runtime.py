"""File logging and one application instance per Windows user data directory."""

from __future__ import annotations

import hashlib
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from PySide6.QtCore import QLockFile, QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from config.paths import data_dir


def configure_logging() -> Path:
    directory = data_dir() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "app.log"
    handlers = [RotatingFileHandler(path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers, force=True)
    # HTTP libraries can log full request URLs; application timing logs suffice.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return path


class SingleInstance(QObject):
    requested = Signal(str)

    def __init__(self, directory: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        directory = directory or data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = QLockFile(str(directory / "app.lock"))
        self.lock.setStaleLockTime(0)
        identity = str(directory.resolve()).casefold().encode("utf-8")
        self.name = "SelectionCopilot-" + hashlib.sha256(identity).hexdigest()[:24]
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)

    def start(self, command: str = "show") -> bool:
        """Own the instance lock, or ask the running instance to show/quit."""
        if not self.lock.tryLock(0):
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if not socket.waitForConnected(3000):
                raise RuntimeError("已有实例正在启动或无响应，请稍后重试。")
            socket.write((command + "\n").encode("ascii"))
            if socket.bytesToWrite() and not socket.waitForBytesWritten(1000):
                raise RuntimeError("无法向已有实例发送命令，请稍后重试。")
            socket.disconnectFromServer()
            return False
        if command == "quit":
            self.lock.unlock()
            return False
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise RuntimeError("无法启动本地实例通信：" + self.server.errorString())
        return True

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.setReadBufferSize(64)
            socket.readyRead.connect(lambda connection=socket: self._read(connection))
            socket.disconnected.connect(socket.deleteLater)
            QTimer.singleShot(3000, socket, socket.disconnectFromServer)
            self._read(socket)

    def _read(self, socket: QLocalSocket) -> None:
        if socket.canReadLine():
            command = bytes(socket.readLine(64)).strip()
            if command in (b"show", b"quit"):
                self.requested.emit(command.decode("ascii"))
            socket.disconnectFromServer()

    def close(self) -> None:
        self.server.close()
        self.lock.unlock()
