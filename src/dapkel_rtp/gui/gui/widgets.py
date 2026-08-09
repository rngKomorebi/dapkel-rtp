"""Widgets shared by more than one tab.

So far: the frame-count picker. How many frames a run may ask for is not a
free choice, so every tab offers the same short list of legal values instead of
a spin box that can land anywhere.
"""

from PyQt5.QtWidgets import QComboBox

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
