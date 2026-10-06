#!/usr/bin/env python3
"""Run the actual distribution QML with the SDK worker, without Basecamp packaging."""
import argparse
import json
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, QUrl, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView

ROOT = Path(__file__).resolve().parents[1]


class SDKBridge(QObject):
    def __init__(self):
        super().__init__()
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read)
        self.process.finished.connect(self.finished)
        self.events = {}
        self.pending = set()
        self.config = None

    def read(self):
        while self.process.canReadLine():
            raw = bytes(self.process.readLine())
            try:
                event = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue  # Native Storage diagnostics share stdout.
            job = event.get("id") if isinstance(event, dict) else None
            if job in self.events and ("progress" in event or "success" in event):
                self.events[job].append(event)
                if "success" in event:
                    self.pending.discard(job)

    def finished(self, *args):
        self.read()
        for job in self.pending:
            self.events[job].append({"id": job, "success": False, "error": "SDK worker stopped"})
        self.pending.clear()

    @Slot(str, str, "QVariantList", result=str)
    def callModule(self, module, method, args):
        try:
            if module != "osm_registry":
                raise ValueError("Unknown module")
            if method == "configure":
                path = str(Path(args[0]).resolve())
                if not Path(path).is_file():
                    raise ValueError("Configuration file does not exist")
                if self.config != path or self.process.state() == QProcess.NotRunning:
                    if self.pending:
                        raise ValueError("Wait for pending jobs before changing configuration")
                    self.close()
                    self.process.start(sys.executable, ["-u", str(ROOT / "modules/osm_registry/maps_sdk.pyz"),
                                                       "--config", path, "worker"])
                    if not self.process.waitForStarted(3000):
                        raise ValueError("Could not start SDK worker")
                    self.config = path
                result = {"success": True}
            elif method == "request":
                if self.process.state() != QProcess.Running:
                    raise ValueError("Connect to a configuration first")
                request = json.loads(args[0])
                job = uuid.uuid4().hex
                request["id"] = job
                self.events[job] = []
                self.pending.add(job)
                self.process.write((json.dumps(request) + "\n").encode())
                result = {"id": job}
            elif method == "poll":
                job = args[0]
                result = self.events.get(job, [])
                if job in self.pending:
                    self.events[job] = []
                else:
                    self.events.pop(job, None)
            else:
                raise ValueError("Unknown SDK method")
            return json.dumps(result)
        except (ValueError, KeyError, IndexError, TypeError) as error:
            return json.dumps({"error": str(error)})

    def close(self):
        if self.process.state() != QProcess.NotRunning:
            self.process.closeWriteChannel()
            if not self.process.waitForFinished(5000):
                self.process.kill()
                self.process.waitForFinished(1000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(ROOT / ".maps/demo-config.json"))
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    app = QGuiApplication(sys.argv[:1])
    bridge = SDKBridge()
    view = QQuickView()
    view.setTitle("Logos Maps — local preview")
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.rootContext().setContextProperty("logos", bridge)
    view.rootContext().setContextProperty("previewConfigPath", str(Path(args.config).resolve()))
    view.setSource(QUrl.fromLocalFile(str(ROOT / "modules/osm_distribution/Main.qml")))
    if view.status() == QQuickView.Error:
        raise SystemExit(1)
    view.resize(1080, 760)
    view.show()

    def finish():
        root = view.rootObject()
        count = root.property("hostedCount")
        if args.screenshot:
            view.grabWindow().save(str(args.screenshot))
        passed = root.property("configured") and not root.property("failed") and count == 3
        print("QML/SDK smoke: " + ("passed (3 hosted fixtures)" if passed else "failed"), flush=True)
        app.exit(0 if passed else 1)

    if args.smoke:
        QTimer.singleShot(5000, finish)
    app.aboutToQuit.connect(bridge.close)
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
