"""
ClearView v2 — Play-while-scanning video guardian
Entry point
"""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from ui.main_window import MainWindow
from ui.first_run_dialog import ensure_first_run
from core.inference_providers import provider_display_name


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ClearView")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("ClearView")

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # First-run: ensure model is present before opening main window
    if not ensure_first_run():
        sys.exit(1)

    window = MainWindow()

    # Show active inference provider in status bar
    provider = provider_display_name()
    window.statusBar().showMessage(f"ONNX · {provider}  |  model: 640m.onnx", 0)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
