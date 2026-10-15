"""M3 dashboard: the title-bar numbers, the reasons behind them, and a way out.

Plain data in (Snapshot plus the counts the window already computed), jump
requests out. This widget measures nothing and mutates nothing on purpose: the
rules live in ``core.suggestions``, so the same verdicts are testable without a
display and reusable by the tray tooltip.
"""
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from . import title_signal
from ..core.suggestions import suggest

LEVEL_EMOJI = {"critico": "🔴", "alto": "🟠", "medio": "🟡"}
TARGET_LABEL = {"memoria": "memória", "ajustes": "ajustes",
                "orfaos": "órfãos", "disco": "disco"}


class SuggestionRow(QWidget):
    def __init__(self, suggestion, on_jump, parent=None):
        super().__init__(parent)
        self.suggestion = suggestion
        self.target = suggestion.target
        self.text_label = QLabel(f"{LEVEL_EMOJI.get(suggestion.level, '·')} "
                                 f"{suggestion.text}")
        self.text_label.setWordWrap(True)
        self.why_label = QLabel(suggestion.why)
        self.why_label.setWordWrap(True)
        self.why_label.setObjectName("why")
        self.jump_button = QPushButton(f"Ir para {TARGET_LABEL.get(suggestion.target, 'aba')}")
        self.jump_button.clicked.connect(lambda _=False: on_jump(suggestion.target))

        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(self.text_label)
        left.addWidget(self.why_label)
        layout = QHBoxLayout(self)
        layout.addLayout(left, 1)
        layout.addWidget(self.jump_button, 0)


class DashboardTab(QWidget):
    def __init__(self, *, on_jump=None, thresholds: title_signal.Thresholds | None = None,
                 parent=None):
        super().__init__(parent)
        self._jump = on_jump or (lambda target: None)
        # the same thresholds the title uses: two signals, one verdict
        self._thresholds = thresholds or title_signal.Thresholds()
        self.rows: list[SuggestionRow] = []

        self.headline = QLabel("Aguardando primeira leitura…")
        self.headline.setObjectName("headline")
        self.details = QLabel("")
        self.details.setWordWrap(True)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(6)
        holder = QWidget()
        holder.setLayout(self.list_box)
        scroll_rows = QVBoxLayout()
        scroll_rows.addWidget(holder)
        scroll_rows.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.headline)
        layout.addWidget(self.details)
        layout.addLayout(scroll_rows)
        layout.addWidget(self.status)

    def show_snapshot(self, snapshot, *, orphan_count: int = 0,
                      thumbnails_kb: int | None = None,
                      extra_notes=()):
        signal = title_signal.compute(snapshot, self._thresholds)
        self.headline.setText(signal.text)
        self.details.setText(self._details(snapshot))
        self._clear_rows()

        for suggestion in suggest(snapshot, orphan_count=orphan_count,
                                  thumbnails_kb=thumbnails_kb):
            row = SuggestionRow(suggestion, self._jump)
            self.rows.append(row)
            self.list_box.addWidget(row)

        notes = [f"não foi possível ler: {e}" for e in snapshot.errors]
        if not self.rows and not notes:
            notes.append("nada a sugerir: memória, pressão, zram e Edge estão "
                         "dentro do orçamento")
        notes.extend(extra_notes)
        self.status.setText(" · ".join(notes))

    def _details(self, snapshot) -> str:
        if snapshot.mem is None:
            return "coleta sem meminfo"
        total = snapshot.mem.mem_total_kb
        avail = snapshot.mem.mem_available_kb
        parts = [f"usada {title_signal.fmt1((total - avail) / title_signal.MB)} GB / "
                 f"{title_signal.fmt1(total / title_signal.MB)} GB",
                 f"livre {title_signal.fmt1(avail / title_signal.MB)} GB",
                 f"app {snapshot.self_rss_kb // title_signal.KB} MB"]
        if snapshot.swap_total_kb:
            pct = snapshot.swap_used_kb * 100 // snapshot.swap_total_kb
            parts.append(f"zram/swap {title_signal.fmt1(snapshot.swap_used_kb / title_signal.MB)} GB "
                         f"({pct}%)")
        if snapshot.pressure_memory:
            parts.append(f"psi/memória avg10 "
                         f"{snapshot.pressure_memory.some_avg10:.1f}".replace(".", ","))
        if snapshot.load:
            parts.append(f"load 1m {snapshot.load.one:.2f}".replace(".", ","))
        if snapshot.apps:
            parts.append("top apps " + ", ".join(
                f"{a.group} {a.rss_kb // title_signal.KB} MB" for a in snapshot.apps[:5]))
        return " · ".join(parts)

    def _clear_rows(self):
        for row in self.rows:
            row.setParent(None)
            row.deleteLater()
        self.rows = []
