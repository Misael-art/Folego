#!/usr/bin/env python3
"""Disposable external-process editor for verify_compact_ui.py, never user data."""
import argparse
import os

from PySide6.QtCore import QObject, Slot, ClassInfo
from PySide6.QtDBus import QDBusConnection
from PySide6.QtWidgets import QApplication, QTextEdit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--caption', required=True)
    args = parser.parse_args()
    app = QApplication([])
    app.setApplicationName('folego-qa-text-target')
    field = QTextEdit()
    field.setWindowTitle(args.caption)
    field.resize(440, 140)
    @ClassInfo(**{'D-Bus Interface': 'org.folego.QAText'})
    class Control(QObject):
        @Slot(result=str)
        def value(self): return field.toPlainText()
        @Slot()
        def focus(self): field.setFocus()
        @Slot()
        def quit(self): app.quit()
    control = Control()
    bus = QDBusConnection.sessionBus()
    assert bus.registerService('org.folego.QAText.p' + str(os.getpid()))
    assert bus.registerObject('/target', control, QDBusConnection.RegisterOption.ExportAllSlots)
    field.show()
    field.setFocus()
    app.exec()


if __name__ == '__main__':
    main()
