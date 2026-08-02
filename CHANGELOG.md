# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-02

### Changed

- Live view now previews an accumulated hitmap instead of a single decoded
  frame, following dapkel's `hitmap_analysis`: every frame the acquisition
  wrote is reduced into one map and the colourbar reads photon rate.
- Live view no longer mirrors the image horizontally, so its orientation
  matches the offline hitmap plots.
- The colour scale spans the full measured range. Hot pixels are shown as
  counted — nothing is clipped, and the scale is not smoothed or carried over
  between refreshes.
- Nothing displayed is estimated. The count-mode rate divides by the exposure
  the GUI set; the timestamp-mode rate divides by the frame period the exe
  measured into `frame_rate_cnt.txt`, and when that is missing or fails its
  consistency check the counted map (frames fired) is shown in its own units
  instead of a rate derived from an assumed frame period.
- Every frame is counted: the previous 5000-frame preview cap is gone. Long
  acquisitions are decoded in chunks instead, so a million-frame acquisition
  costs bounded memory rather than being truncated or running out of it.
- The live view keeps acquiring until Stop. A failed acquisition — the exe
  exiting non-zero, an exe that cannot be started, a 0-byte/short/undecodable
  `.bin`, a failed quadrant reprogram, or an unexpected error — is reported and
  retried after a short pause, instead of ending the preview.
- In 64x64 mode each quadrant is normalised by the frames that quadrant
  delivered rather than rescaled onto a common frame count, and the title
  reports the spread when they differ.
- Disabled line edits, combo boxes and spin boxes are now dimmed like the
  buttons already were; previously they looked live while ignoring every
  click. Affects every tab.

### Fixed

- Live view picks the reduction from the loaded program, as
  `hitmap_analysis` does. For the timestamp programs (`ORT`, `S*T`, `C*T`, the
  OR/coincidence programs) `unpack`'s `photon_counts` holds coarse-timestamp
  bits, not counts; summing it weighted every firing by a random 1..~90, which
  showed up as speckle, a peak that jumped between refreshes and column
  structure. Those programs now use the occupancy reduction
  (frames with a valid timestamp) and a rate in Hz, bounded by the one
  firing per frame period the readout can report; the `*C` programs keep the
  summed-count reduction and cps.
- Frames that carry no data are excluded from the hitmap and from the rate
  normalisation. The `.bin` is a fixed 16 MiB DDR3 dump, so it contains both
  slots the acquisition never wrote (all-zero) and idle-pattern frames from
  before data started flowing (every word identical — 152 of 800 on one
  acquisition). Counting them diluted the rate by however many a pass happened
  to begin with, dimming and brightening the whole map between refreshes.
- Live view snapshots `nframes`/exposure once per pass. Both were read from the
  worker's params dict twice — once for the acquisition, once for the decode —
  while the spinboxes can mutate them from the GUI thread in between, so an
  edit mid-pass could have the decode read frames that pass never wrote and
  mix in the previous acquisition's data.
- The live-view `.bin` is emptied before each acquisition, so a pass that
  writes fewer frames than the one before it cannot leave the previous
  acquisition's frames in the tail of the fixed-size buffer to be accumulated
  as if they were current.
- The live-view worker always signals completion, even if it hits an internal
  error. Previously an unhandled exception in the worker thread left the tab
  with Stop enabled and no frames arriving, which looked exactly like the
  acquisition having stopped for no reason.

### Added

- **Data Quality tab.** Point it at the folder being acquired into, pick one
  of the `.bin` files it lists, press Run: the file is decoded and its TDC-code
  distribution is shown, the check `dapkel.functions.data_quality` runs
  offline, now available in the app that took the data. It answers the one
  question worth answering while the camera is still set up — did the TDC
  actually record timing? — which otherwise fails silently, `unpack` returning
  plausible integers and every downstream analysis still producing a shape.
  Codes can be pooled over the whole array or histogrammed for one pixel, and
  the per-pixel valid-timestamp map beside the histogram shows whether the
  timing came from the whole sensor or a corner.
- `dapkel_rtp.functions.data_quality` — file listing with frame counts and
  program tags, chunked accumulation of a file's exact per-code histogram
  (so pooling every pixel of a million-frame acquisition costs a fixed ~64 kB
  instead of a billion values), the statistics drawn from it, and a
  three-way verdict.
  - No verdict is given for a `*C` (count) file, where the bits decoded here
    are photon counts rather than time and still make a plausible-looking
    distribution — nor for a file whose name carries no program tag, until
    you say which program wrote it. The numbers are always reported either
    way; only the verdict waits on knowing what it is judging.
  - The verdict thresholds are heuristics over those reported numbers, not
    physics, and are named constants in one place. A narrow spread is only
    ever `SUSPECT`, never `FAIL`: a pulsed source at a fixed delay
    legitimately concentrates the first-photon times.
  - Frames that carry no data are dropped structurally, by the same
    `hitmap.valid_frame_mask` the live view uses, so the unwritten tail of
    the fixed-size DDR3 dump is not counted as frames that failed to record.
- `dapkel_rtp.functions.hitmap` — the two hitmap reductions, dead-frame
  detection, chunked accumulation, photon-rate conversion (cps/Hz) and the
  full-range colour limits.
- `dapkel_rtp.functions.unpack.unpack` — shift/mask decoder, bit-for-bit
  identical to `unpack_kelpie_binary_data` but ~10x faster, with options to
  skip timestamp decoding and to start at a given frame. Together those are
  what make counting every frame of an acquisition per refresh affordable.

## [0.0.1] - 2026-07-05

Initial commit.

### Added

- GUI, functions for starting single acquisition and a chain of acquisitions, and a live view tab.
