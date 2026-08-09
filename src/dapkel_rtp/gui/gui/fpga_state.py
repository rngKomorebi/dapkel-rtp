"""What is actually loaded on the FPGA, shared by every tab that programs it.

The FPGA holds one bitstream and one program at a time, and three tabs can
reprogram it — Single Acquisition, Chain Acquisition and Live View. Each used to
cache that state privately, so reprogramming from one tab left the others
believing something that was no longer true: hit Run on the acquisition tab
after a live-view session and the run went ahead with whatever program live view
had left loaded, because the acquisition tab's cached value still matched its own
combo box.

That was already wrong for the program alone. It matters more now that the
firmware version is recorded in ``metadata.json``: a stale belief would be
written down as fact.

So the state lives here, once, and a tab that reprograms publishes it. Tabs
react to someone else's change by disabling Run until Power Mgt has been run
again — deliberately *not* by reprogramming themselves, which would have two
tabs racing to drive the same hardware off one signal.

``Live View`` clears the state rather than publishing one: in 64x64 mode it
reprograms per quadrant inside its worker loop, so when it stops, what is loaded
is whichever quadrant happened to be last. Unknown is the honest answer, and it
makes the next run on any other tab reprogram.
"""

from PyQt5.QtCore import QObject, pyqtSignal


class FpgaState(QObject):
    """The (program path, firmware version) pair currently on the FPGA."""

    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._loaded: tuple[str, str] | None = None

    @property
    def loaded(self) -> tuple[str, str] | None:
        """The loaded pair, or None when nothing is known to be loaded."""
        return self._loaded

    def set_loaded(self, program: str, firmware: str) -> None:
        """Record a successful programming run. Emits 'changed' if it moved."""
        pair = (program, firmware)
        if pair != self._loaded:
            self._loaded = pair
            self.changed.emit()

    def clear(self) -> None:
        """Forget what is loaded — for when it is about to become unknowable."""
        if self._loaded is not None:
            self._loaded = None
            self.changed.emit()


# One FPGA, one state. The tabs build themselves with no way to be handed
# shared objects, so this is a module-level singleton rather than plumbing.
FPGA = FpgaState()
