"""Scrollable literal review text and a default-negative confirmation."""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout
from PySide6.QtGui import QGuiApplication


def confirm_text(title, text, parent=None):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    screen = parent.screen() if parent is not None else QGuiApplication.primaryScreen()
    area = screen.availableGeometry() if screen is not None else None
    dialog.resize(min(680, area.width() - 40) if area else 680,
                  min(480, area.height() - 60) if area else 480)
    content = QPlainTextEdit()
    content.setReadOnly(True)
    content.setPlainText(text)
    content.setAccessibleName("Alvos, limites e código da operação em revisão")
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No)
    buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Confirmar")
    buttons.button(QDialogButtonBox.StandardButton.No).setText("Cancelar")
    buttons.button(QDialogButtonBox.StandardButton.Yes).setAutoDefault(False)
    buttons.button(QDialogButtonBox.StandardButton.No).setAutoDefault(False)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    box = QVBoxLayout(dialog)
    box.addWidget(content, 1)
    box.addWidget(buttons)
    buttons.button(QDialogButtonBox.StandardButton.Yes).setDefault(False)
    buttons.button(QDialogButtonBox.StandardButton.No).setDefault(True)
    buttons.button(QDialogButtonBox.StandardButton.No).setFocus()
    return dialog.exec() == QDialog.DialogCode.Accepted
