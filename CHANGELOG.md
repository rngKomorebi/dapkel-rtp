# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-08-09

### Investigated: a `.bin` holds more frame slots than the run asked for

Settled, so it does not need asking a third time. The operator enters 10 000
frames and every file measured is 16 384 frame slots. **The camera records
exactly the 10 000 asked for.** Slots 10 000–16 383 are a **byte-exact replay of
slots 1 808–8 191** — offset exactly 8 192 frames, which is 16 MiB.

Measured by hashing all 16 384 slots of each file: exactly 10 000 unique, first
duplicate pair `(1808, 10000)`, one distinct repeat offset `[8192]`. Identical in
`2026.07.22/SPDC_ORT1/2/50/100.bin`, `2026.07.24`, `2026.07.27`, `2026.07.31`
(`ORC`, count mode) and `2026.08.03` — and `slots[10000:16384] ==
slots[1808:8192]` holds byte-for-byte on the count-mode `2026.06.29`,
`2026.07.03` and `2026.07.08` DCR files too. Timestamp and count programs,
internal and external trigger, weeks apart: deterministic plumbing, not residue.

The file size is quantised to 16 MiB blocks, `slots = 8192 * ceil(nframes /
8192)` — not "the next power of two", which the 800-frame live-view file
(8 192 slots) rules out. The exe's own transfer size `ep 0x07 = nframes*512 - 8`
= 20 479 968 B is *smaller* than the 33 554 432 B file, so the length comes from
the exe's buffer, not that register. And because the duplicates are perfectly
frame-aligned across every file, there is no 32-byte shortfall anywhere: the
`-8` is benign and the last frame is complete.

Consequences, stated precisely because they are easy to overstate:

- Nothing is being discarded and there is **no extra data**. Re-analysing at
  16 384 frames would double-count 6 384 frames per file — inflating counts ~64 %
  and injecting duplicated timestamps into every histogram.
- The photon rate was already right, and for a better reason than
  self-consistency: `accumulate_hitmap`'s `read = min(nframes, frames_in_file)`
  reads exactly the real frames.
- `nframes * frame_acq_time` is the correct camera time. It is not 1.64× short.
- Host side is clean: `worker.py` passes the spin box value to `argv[3]`
  verbatim, with no rounding anywhere.

Wall clock, from file mtimes: the 100-file 2026-07-22 batch took 68.2 s, median
0.649 s per acquisition, against 96.85 ms of camera time per file — a **~14 %
duty cycle**.

### The existing data is all short_exposure

That wall clock excludes a millisecond-scale frame for the 2026-07-22 batch
(10 000 frames at a 10 ms frame would be 100 s per file, not 0.65 s), which
contradicted the belief that it was long-exposure data. The bitstreams settle it:
`params/camera/short_exposure/bitfile/Kelpie_top.bit` is **byte-identical** to
the legacy `params/camera/bitfile/Kelpie_top.bit` that every run so far was taken
with (sha256 `8c8d6d59f1716369…`, 2 895 KB), while the long-exposure bitstream is
a different file (`ed35696cc2640258…`, 2 776 KB).

So every `.bin` on the drive was acquired with the short-exposure firmware: a
fixed 9 µs frame, consistent with the ~9.7 µs the counter reads back and with the
0.65 s-per-file wall clock. Nothing has yet been taken in long-exposure mode.

### Investigated: the live-view rate does not depend on the frame count

Raised because the previewed rate visibly moves when `Frames/acq` changes, which
it must not — more frames buy precision, not a bigger number. The reduction is
clean; the *summary statistics on screen* were the ones moving.

Measured on `2026.08.07/SPDC_10MHz/SPDC_10MHz_S0T101.bin` (8192 frames, all
carrying data), reading prefixes of 50 → 8192 frames of the **same** file, so
the light is identical by construction:

| frames | one count | mean | median | max |
|-------:|----------:|-----:|-------:|----:|
| 50 | 100 kHz | 24.2 kHz | 0 | 1.60 MHz |
| 200 | 25 kHz | 22.1 kHz | 0 | 1.28 MHz |
| 1000 | 5 kHz | 22.6 kHz | 5.00 kHz | 1.27 MHz |
| 8192 | 610 Hz | 22.5 kHz | 7.32 kHz | 1.33 MHz |

The mean is flat to ±2 % over a 164× range of frame counts — and ±0.6 % across
six consecutive files at 8192 frames (22.34–22.60 kHz), so that ±2 % *is* the
counting noise, not a trend. The rate is nframes-invariant, as it should be.

The median and the max are not, and cannot be. A pixel that fired `k` times in
`N` frames reads `k / (N * shutter)`, so the map is a grid of that step: 100 kHz
per count at 50 frames, 610 Hz at 8192, against a median pixel of ~7.3 kHz. At
50–200 frames the median pixel has not fired at all and reads 0; at 1000 it has
fired once and reads one whole rung, 5 kHz. The max is the extreme of 1024 such
estimates and sets the colourbar top, so the entire colour scale moves with it.

Rule of thumb: the median pixel here fires once per ~680 frames, so ~68 000
frames are needed for 10 % on a single pixel. The mean reaches that in tens.

### Added

- `metadata.json` beside every acquisition, one record per run, appended to a
  `runs` array so a folder can hold several (a `Start#` continuation, or two
  chain jobs sharing a folder). Written by `AcquisitionWorker` from the
  parameters it actually passed to the exe, so it cannot drift from what ran.
  Written once after the first file with `status: "running"` and again at the end
  with the outcome (`completed` / `aborted` / `failed`), both under the same
  `run_id`; a leftover `"running"` means the app never got to finish. Atomic
  (temp + replace), and an existing `metadata.json` this app did not write is
  never overwritten — the record goes to `metadata_dapkel_rtp.json` instead.
- The record carries the `readout` block above — requested `nframes` *and* the
  raw file shape side by side, since those two disagreeing is the whole story
  and keeping one destroys the evidence. `readout.verified` byte-compares the
  tail of the run's first file once per run, so a firmware change shows up
  instead of being assumed away.
- Firmware selector (`short_exposure` / `long_exposure`). `Kelpie_v2_pwr_mgt.exe`
  takes no bitstream argument — it opens the hardcoded relative path
  `./bitfile/Kelpie_top.bit` — so a version is chosen by launching it from
  `params/camera/short_exposure/` or `params/camera/long_exposure/`, each with
  its own `bitfile/`. Nothing is copied or overwritten and both bitstreams stay
  inspectable. Changing the selection reprograms the FPGA immediately, exactly as
  changing the program already did. Until a bitstream is placed the app falls
  back to the legacy `params/camera/bitfile/` and says so, and the record marks
  `firmware_bitfile_source` accordingly.
- Bias-voltage box (default 22 V, 0 shows blank and records `null`). The app
  cannot set the supply; this is the first time the number has been recorded
  anywhere machine-readable — until now it lived only in folder names like
  `22V`.
- The acquisition tab shows the derived frame length and the run's total camera
  time, and the chain tab shows them per job. It is the number that says whether
  a run takes 0.1 s or 100 s.
- `hitmap.independent_frames` measures where the replay starts without needing a
  record, and `hitmap.tail_is_replay` checks it exactly when `nframes` is known.
- `functions/timing.py` — the one place that answers how long a frame takes and
  how long its shutter is open. The frame length used to be derived three
  different ways (a counter file, the exposure register, a hardcoded 9 µs), which
  is how the app came to disagree with itself and with `dapkel`. The firmware
  vocabulary and the 9 µs readout constant were also defined in three files;
  now once.
- Live View has the same firmware selector as the acquisition tabs, and shows the
  frame length its rate divides by. It needed one: without knowing the firmware
  the previewed colourbar has no defensible unit, which is what reading it out of
  `frame_rate_cnt.txt` amounted to.

### Changed

- Two keys describe the timing, and they describe both firmware versions with no
  nulls: `open_shutter_time_s` (how long the shutter is open in one frame — the
  register times 5 ns, in *both* versions) and `frame_acq_time_s` (how long one
  frame takes: a fixed 9 µs under `short_exposure`, `open_shutter + 9 µs` under
  `long_exposure`). This deliberately does **not** reuse `dapkel`'s
  `frame_cycle_s` / `exp_time_s` / `exposure_window_s` triple, which needs a null
  in every record and puts two near-identical names on two different quantities.
  Nothing reads an rtp acquisition record yet, so the divergence costs nothing
  today; when the two are wired together, `dapkel` learns these names. Do not
  "fix" it back. `firmware_version` keeps `dapkel`'s exact vocabulary, because
  that one *is* shared.
- `wallclock_time_s` keeps `dapkel`'s meaning — `total_frames *
  frame_acq_time_s`, derived camera time. The measured host duration is a
  separate key, `wallclock_time_measured_s`. They differ by 7× on real data, so
  one name for both would make every rate wrong by that factor.
- The acquisition tab's `Exp` box is now `Shutter:` and is capped at 9 µs under
  `short_exposure`, where a longer value is meaningless; it becomes
  `Shutter X:` with no cap under `long_exposure`. A cap that moves the operator's
  value is logged, never applied silently.
- Data Quality lists file sizes in *slots*, not "frames" — the count is the
  block-padded file size, never a frame count.
- **Frames is a picker, not a free number**, on Acquisition, Chain Acquisition
  and Data Quality: 8192, 16 384, 24 576, 32 768 — whole 16 MiB readout blocks
  (`gui.widgets.FRAME_BLOCK`). A run that stops mid-block leaves the surplus
  slots replaying earlier frames, which is the whole subject of the first
  section above; offering only multiples removes the way in. Data Quality keeps
  its `all` entry. Live View deliberately keeps a free spin box: it throws every
  pass away, so a mid-block stop never reaches a file anyone keeps, and the
  frame count there is a refresh-rate choice.
- **Both live-view rates now divide by the live (shutter-open) time**, which is
  what `dapkel` divides by, so the two modes are comparable with each other and
  with the offline rate map: `rate = hitmap / (frames * live_per_frame)`, where
  `live_per_frame` is the open shutter under `short_exposure` (only that window
  of the fixed 9 µs frame is photon-sensitive; the rest is readout) and the whole
  `shutter + 9 µs` frame under `long_exposure`. This mirrors
  `dapkel.core.timing.resolve_live_time`'s `short_window` / `full_window` split.
  Two changes in one:
  - `MODE_TIMESTAMP` divided by a frame period read out of
    `frame_rate_cnt.txt`, and showed no rate at all when that file was missing or
    failed its plausibility check. Nothing reads that counter now, so a rate is
    always available and always defensible.
  - `MODE_COUNT` divided by the shutter already, and keeps doing so — the
    intermediate version of this branch moved it to `frame_acq_time` on the
    mistaken belief that `dapkel` normalised by the frame. It does not: it
    divides by `nframes * n_files * acq_window`.
  A zero shutter under `short_exposure` leaves nothing trustworthy to divide by
  (register 0 still returns counts, so the true window is unknown, not zero), so
  the counted map is shown instead of a rate invented from a default.
  One deliberate difference from `dapkel` remains: `frames` here is the number of
  frames that *carried data*, not the number requested, so a pass that starts
  with idle frames does not dim the whole map. `dapkel` divides by the requested
  `nframes`, so it reads lower than the live view by that fraction.
- Live View leads with the **mean** rate over the array, then median and max,
  and the status line says what one photon is worth (`one count = 5e+03 Hz`).
  The mean is the one number that does not move with `Frames/acq`; the other two
  are grid artefacts at low frame counts, per the section above. The `Frames/acq`
  tooltip now says so at the control itself.
- Live View's shutter default was 20 µs, which under `short_exposure` is longer
  than the whole 9 µs frame — it can only ever have been a long-exposure value or
  a number the firmware ignored. Now 0.1 µs, the operator's stated typical
  window.
- `hitmap.resolve_frame_period` is gone, with `_READOUT_FLOOR_S` and
  `_PERIOD_CEILING_S`, the plausibility guard that existed only to sanity-check
  the counter. `live_time_per_frame(mode, firmware_version, open_shutter_time_s)`
  replaces the old `(mode, exposure, folder, nframes)` signature — it no longer
  needs a folder, because it no longer reads anything from disk.

### Fixed

- Data Quality's `Frames = all` read every slot in the file, so on a
  10 000-frame acquisition it histogrammed 6 384 frames twice — 39 % of every
  default-setting check was duplicated entries. It now measures where the replay
  starts and stops there, and the report says which limit it used and why.
- No measurement data ships in the release or reaches git. `main.spec` bundled
  the whole `functions/helpers` folder, which is also the app's default output
  path, so every acquisition sitting there went into the exe —
  `live/live.bin` alone was 16 MB of stale preview data. The four vendor
  binaries are now listed individually and the payload is 9.1 MB instead of
  25.9 MB. `.gitignore` gained `*.bin` (the two folder rules only covered the
  default paths, so an acquisition taken anywhere else in the tree was still
  offerable to `git add`) and `frame_rate_cnt.txt`. Nothing of the kind was
  tracked, so this is a guard, not a removal.
- Data Quality creates its default folder before the first scan. It used to
  exist only because the release bundled it — with stale acquisitions inside —
  so dropping that would have opened the released app on `⚠ Not a folder`.
- Each tab cached the FPGA's loaded program privately, so reprogramming from one
  tab left the others believing something untrue: hitting Run on the acquisition
  tab after a live-view session went ahead with whatever program live view had
  left loaded. The state now lives in one place (`gui/fpga_state.py`); a tab that
  reprograms publishes it, and the others disable Run until Power Mgt has been
  run again rather than reprogramming themselves and racing for the board. Live
  View clears the state instead of publishing one — in 64×64 mode it reprograms
  per quadrant inside its worker loop, so what is loaded when it stops is not
  knowable, and unknown is the honest answer.

### Removed

- **Nothing in the app reads `frame_rate_cnt.txt`.** `grep -rn frame_rate_cnt`
  over `gui/` and `functions/` now returns only this CHANGELOG, the two reference
  scripts flagged below, and prose explaining why it is not used. The exe keeps
  writing the file and the app leaves it alone.

  It is not usable as a frame period. Across the group's drive it holds 11
  distinct values, it is overwritten by every acquisition so only the last
  survives, and it does not track the exposure register coherently: the
  50/100/200/500 ns sweep preserved in `2026.07.31/hitmap test` reads 9.700,
  9.710, 9.700 and 9.770 µs per frame — not monotonic, and 50 → 500 ns moves the
  period by 70 ns where the register asks for 450 ns. One live-view folder's
  value implies ~8 300 frames for a file holding ~500.

  Under the `dapkel` reading (total ticks ÷ `nframes`) the large values do land
  at 9.685–9.770 µs, which is why the period was believable for so long.

### Flagged, not fixed

- `matlab/extract_DCR.m` carries a warning header: it reads the counter as ticks
  *per frame*, so its frame period is a factor of `nframes` too long — 96.85 ms
  instead of 9.685 µs — making every DCR it prints 10 000× too small. The ports
  `extract_dcr.py` and `dcr_hitmap.py` share the error. These are reference
  copies of what the group runs, so nothing was corrected on the operator's
  behalf; the decision is theirs.
- `functions/tools/exposure_sweep.py` conclusions are marked **unproven**. Its
  channel 1 was that same counter, so "the frame period did not move, therefore
  the firmware ignores the exposure register" was never supported — the
  instrument reading the period had no resolution to speak of. Its counts channel
  is unaffected. Re-deriving needs host wall-clock timing or a scope on the frame
  trigger.

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
