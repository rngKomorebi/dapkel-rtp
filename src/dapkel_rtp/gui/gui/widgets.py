"""Widgets shared by more than one tab.

Two so far:

* the frame-count picker — how many frames a run may ask for is not a free
  choice, so every tab offers the same short list of legal values instead of a
  spin box that can land anywhere;
* 'TimedProgressBar' — the progress bar every long-running tab uses, which says
  how long the run has taken and how much is left, in text that stays readable
  wherever the filled bar happens to end.
"""

from __future__ import annotations

import time

from PyQt5.QtCore import QRect, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QComboBox, QProgressBar

from .style import BG_DEEP, TEXT

# The readout hands data over in 16 MiB blocks of 8192 frames
# (functions.hitmap.REPLAY_BLOCK_FRAMES). A run that is not a whole number of
# blocks still fills the last one: the surplus slots are a byte-exact replay of
# the slots 8192 earlier, which a naive read counts twice. Asking only for
# multiples of the block keeps every file exactly as long as it claims to be.
FRAME_BLOCK = 8192

# Four steps for now; extend the range when longer runs are wanted.
FRAME_CHOICES = tuple(FRAME_BLOCK * n for n in range(1, 5))  # 8192 … 32 768

DEFAULT_NFRAMES = 2 * FRAME_BLOCK  # 16 384

FRAMES_TIP_BLOCK = (
    "Frames go in whole 8192-frame readout blocks (16 MiB each).\n"
    "A run that stops mid-block leaves the surplus slots replaying\n"
    "earlier frames, so only multiples are offered."
)


def _label(n: int) -> str:
    """Group thousands with a space: 16384 → '16 384'."""
    return f"{n:,}".replace(",", " ")


def make_nframes_combo(
    default: int = DEFAULT_NFRAMES,
    *,
    all_option: bool = False,
    width: int = 90,
) -> QComboBox:
    """A combo of the legal frame counts; ``currentData()`` gives the int.

    *all_option* prepends an "all" entry carrying 0, for the tabs that read a
    file rather than acquire one and can be told to take whatever is in it.
    """
    combo = QComboBox()
    if all_option:
        combo.addItem("all", 0)
    for n in FRAME_CHOICES:
        combo.addItem(_label(n), n)
    idx = combo.findData(default)
    combo.setCurrentIndex(idx if idx >= 0 else combo.findData(FRAME_CHOICES[0]))
    combo.setFixedWidth(width)
    return combo


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------


def format_duration(seconds: float) -> str:
    """Seconds as ``m:ss``, or ``h:mm:ss`` once past an hour."""
    total = int(round(max(0.0, seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class TimedProgressBar(QProgressBar):
    """A progress bar that reads its own clock, in text legible either side.

    Two things Qt's own bar does not do:

    * **The text stays readable.** A stylesheet gives ``QProgressBar`` a single
      text colour for the whole width, so any choice is unreadable on one side
      of the fill boundary -- light ink vanishes into the cyan chunk, dark ink
      into the empty groove. The text is painted here instead, twice with the
      same glyph positions and complementary clips: dark over the filled part,
      light over the rest. Every character keeps its contrast wherever the
      boundary happens to sit.
    * **It says how long.** Time spent and an estimate of the time left, so a
      run of a few thousand frames per file can be left alone and still be
      answerable about when it will be done. The estimate extrapolates from the
      progress made so far, so it only appears once there is progress to
      extrapolate from; until then the bar says so rather than inventing a
      number.

    Drive it with 'begin' / 'setValue' / 'end'; ``set_prefix`` puts a caller's
    own words ("Job 2/5 S3C") in front of the numbers.
    """

    # Progress may arrive minutes apart -- one tick per half second keeps the
    # elapsed time moving in between without costing anything noticeable.
    _TICK_MS = 500

    # Below this fraction an extrapolation is mostly startup cost multiplied by
    # a large number, which reads as a wildly wrong estimate rather than as a
    # rough one.
    _MIN_FRACTION = 0.02
    _MIN_ELAPSED_S = 1.0

    _SEP = "   ·   "

    # Groove height, set here rather than at each call site. The bar carries a
    # line of monospaced text three points above the rest of the UI (style's
    # '_bar'), and 22px -- what all three call sites used to pin with
    # setFixedHeight, each repeating the number -- is too tight at that size.
    # Kept as a minimum, not fixed, so a larger base_fs can still grow the bar
    # instead of cropping its own text.
    _MIN_HEIGHT = 28

    def __init__(self, parent=None, *, idle_text: str = "Ready"):
        super().__init__(parent)
        # Qt must not paint the text: this class does, in paintEvent.
        self.setTextVisible(False)
        self.setMinimumHeight(self._MIN_HEIGHT)
        self._idle_text = idle_text
        self._prefix = ""
        self._frozen: str | None = idle_text
        self._t0: float | None = None
        self._ticker = QTimer(self)
        self._ticker.setInterval(self._TICK_MS)
        self._ticker.timeout.connect(self.update)

    # ------------------------------------------------------------------
    # Run state
    # ------------------------------------------------------------------

    def begin(self, prefix: str = ""):
        """Reset to zero and start counting."""
        self._prefix = prefix
        self._frozen = None
        self._t0 = time.monotonic()
        self.setValue(self.minimum())
        self._ticker.start()
        self.update()

    def end(self, text: str | None = None):
        """Stop counting and freeze *text* -- with how long it took appended.

        Called for every ending, finished or not: the value is left where it
        got to, so an aborted run still shows how far it came.
        """
        took = self.elapsed()
        self._ticker.stop()
        self._t0 = None
        if text is None:
            self._frozen = self._idle_text
        elif took is None:
            self._frozen = text
        else:
            self._frozen = f"{text}{self._SEP}took {format_duration(took)}"
        self.update()

    def set_prefix(self, prefix: str):
        """Words to show before the numbers, for the rest of this run."""
        self._prefix = prefix
        self.update()

    def set_idle(self, text: str):
        """Replace the text shown while no run is in progress."""
        self._idle_text = text
        if self._t0 is None:
            self._frozen = text
            self.update()

    def elapsed(self) -> float | None:
        """Seconds since 'begin', or None when no run is in progress."""
        if self._t0 is None:
            return None
        return time.monotonic() - self._t0

    # ------------------------------------------------------------------
    # Text
    # ------------------------------------------------------------------

    def _fraction(self) -> float:
        span = self.maximum() - self.minimum()
        if span <= 0:
            return 0.0
        return min(1.0, max(0.0, (self.value() - self.minimum()) / span))

    def text(self) -> str:  # noqa: D102 - overrides QProgressBar.text
        if self._frozen is not None:
            return self._frozen
        frac = self._fraction()
        parts = []
        if self._prefix:
            parts.append(self._prefix)
        parts.append(f"{frac * 100:.0f}%")
        spent = self.elapsed()
        if spent is not None:
            parts.append(f"{format_duration(spent)} elapsed")
            if frac >= 1.0:
                pass  # nothing left to estimate; 'end' has the total
            elif frac >= self._MIN_FRACTION and spent >= self._MIN_ELAPSED_S:
                left = spent * (1.0 - frac) / frac
                parts.append(f"~{format_duration(left)} left")
            else:
                parts.append("estimating…")
        return self._SEP.join(parts)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        super().paintEvent(event)  # groove and chunk, no text
        label = self.text()
        if not label:
            return

        # The stylesheet's chunk fills the contents rect left to right in
        # proportion to the value, so the same proportion of the same rect is
        # where the dark ink belongs.
        inner = self.contentsRect()
        boundary = inner.left() + int(round(inner.width() * self._fraction()))
        whole = self.rect()

        filled = QRect(
            whole.left(), whole.top(), boundary - whole.left(), whole.height()
        )
        empty = QRect(
            boundary, whole.top(), whole.right() - boundary + 1, whole.height()
        )

        painter = QPainter(self)
        painter.setFont(self.font())
        for colour, clip in ((BG_DEEP, filled), (TEXT, empty)):
            if clip.width() <= 0:
                continue
            painter.setPen(QColor(colour))
            painter.setClipRect(clip)
            # Both passes lay the text out in the *same* rect, so the glyphs
            # land in identical positions and only their colour differs.
            painter.drawText(whole, Qt.AlignCenter, label)
        painter.end()
