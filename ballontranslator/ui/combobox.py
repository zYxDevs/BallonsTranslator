from qtpy.QtWidgets import QComboBox
from qtpy.QtCore import Signal, Qt
from qtpy.QtGui import QDoubleValidator, QFocusEvent, QKeyEvent

from typing import List

class SizeComboBox(QComboBox):
    
    apply_change = Signal(float)
    def __init__(self, val_range: List = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.text_changed_by_user = False
        self.editTextChanged.connect(self.on_text_changed)
        self.currentIndexChanged.connect(self.on_current_index_changed)
        self.setEditable(True)
        self.min_val = val_range[0]
        self.max_val = val_range[1]
        validator = QDoubleValidator()
        if val_range is not None:
            validator.setTop(val_range[1])
            validator.setBottom(val_range[0])
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)

        self.setValidator(validator)
        self.lineEdit().setValidator(validator)
        self._value = 0

    def keyPressEvent(self, e: QKeyEvent) -> None:
        key = e.key()
        if key in [Qt.Key.Key_Return, Qt.Key.Key_Enter]:
            self.check_change()
        super().keyPressEvent(e)

    def focusInEvent(self, e: QFocusEvent) -> None:
        super().focusInEvent(e)
        self.text_changed_by_user = False

    def on_text_changed(self):
        if self.hasFocus():
            self.text_changed_by_user = True

    def on_current_index_changed(self):
        if self.hasFocus():
            self.check_change()

    def value(self) -> float:
        txt = self.currentText()
        try:
            val = float(txt)
            self._value = val
            return val
        except:
            return self._value

    def setValue(self, value: float):
        value = min(self.max_val, max(self.min_val, value))
        self.setCurrentText(str(round(value, 2)))

    def check_change(self):
        if self.text_changed_by_user:
            self.text_changed_by_user = False
            self.apply_change.emit(self.value())