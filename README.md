## Data Analysis Package for KELpie - Real-Time Plotting (DAPKEL_RTP)

Package with an application for data acquisition and real-time plotting of sensor population for the Kelpie detector. 

<!-- ![Tests](https://github.com/rngKomorebi/LinoSPAD2/actions/workflows/tests.yml/badge.svg)
![Documentation](https://github.com/rngKomorebi/LinoSPAD2/actions/workflows/documentation.yml/badge.svg)
![PyPI - Version](https://img.shields.io/pypi/v/daplis)
![PyPI - License](https://img.shields.io/pypi/l/daplis) -->

## Introduction

The Kelpie detector was developed at EPFL by Dr. Tommaso Milanese. It features a 64x64 Single-Photon Avalanche Device (SPAD) sensor with a 2x2 macropixel building block. It is fully reprogrammable, with high PDE across whole visible spectrum with a peak at 780 nm, 40 ps (rms) jitter, low dark count rate (DCR) and reasonable cross-talk.

This package was derived from the original functions written in Matlab by Dr. Milanese for starting the data acquisition and real-time plotting of the camera's hitmap

## Structure of the package

The "functions" folder holds all functions from unpacking to plotting numerous types of graphs (pixel population, histograms of timestamp differences, etc.)

The "gui" folder hold python code for the app itself including the contents of each tab.

The "params" tab hold the programs for programming the SPADs and the bitfile data for communicating with the camera.

The standalone repo for the offline data unpacking and analysis can be found [here](https://github.com/rngKomorebi/dapkel).

## The app

Four tabs, all writing into a folder you choose:

- **Single Acquisition** — run `Kelpie_v2.exe` *N* times into one folder.
- **Chain Acquisition** — a queue of jobs, each with its own program, frame
  count and shutter time, reprogramming the FPGA between them as needed.
- **Live View** — continuous hitmap preview, 32×32 or a stitched 64×64 from the
  four quadrant programs.
- **Data Quality** — decode one `.bin` and check that the TDC actually recorded
  timing. That failure is silent otherwise: the decode returns plausible
  integers either way.

### Firmware versions

Two bitstreams exist, and which one is loaded changes what a frame is:

| | frame length | the shutter box means |
|---|---|---|
| `short_exposure` | fixed 9 µs | the window inside that frame (50–500 ns typically) |
| `long_exposure` | shutter + 9 µs | the window, with 9 µs of readout appended |

`Kelpie_v2_pwr_mgt.exe` takes no bitstream argument — it opens the hardcoded
relative path `./bitfile/Kelpie_top.bit` from its working directory. A version
is therefore selected by *which folder the exe is launched from*:

```
src/dapkel_rtp/params/camera/short_exposure/bitfile/Kelpie_top.bit
src/dapkel_rtp/params/camera/long_exposure/bitfile/Kelpie_top.bit
```

Put each bitstream in its folder under that exact name. Nothing is copied or
overwritten, so both stay intact and it is unambiguous which was loaded. Until a
file is placed the app falls back to the legacy `params/camera/bitfile/` and says
so in the log. Changing the selection reprograms the FPGA immediately, as
changing the program already does.

### Every acquisition writes a `metadata.json`

One record per run in the output folder, describing how, where and when the data
was taken — frame count, shutter time, firmware and its bitstream hash, chip
config, program file, bias voltage, timestamps, measured and derived durations.
A folder can hold several runs, so the file is a `runs` array; a `metadata.json`
this app did not write is never overwritten.

Two keys carry the timing, and they mean the same thing under both firmware
versions:

- `open_shutter_time_s` — how long the shutter is open in one frame.
- `frame_acq_time_s` — how long one frame takes.

`wallclock_time_s` is `total_frames * frame_acq_time_s`, i.e. **camera** time,
matching `dapkel`'s key of the same name. The measured host duration is the
separate `wallclock_time_measured_s`; on real data the two differ by ~7×.

### A `.bin` holds more frame slots than you asked for

The readout is quantised to 16 MiB blocks, so a 10 000-frame run lands in a
16 384-slot file. **The extra slots are not extra data** — they are a byte-exact
replay of the slots 8192 earlier. A 10 000-frame file holds exactly 10 000
distinct frames and 6 384 copies, verified across every dataset the group has
taken. Read only the first `nframes`; reading the whole file counts real frames
twice. See the CHANGELOG for the measurements.

Consequently: never infer a frame count from a file size, and treat the slot
count the Data Quality tab lists as a size, not a frame count.

### `frame_rate_cnt.txt`

`Kelpie_v2.exe` writes this next to every acquisition and nothing in the app
reads it. It is not a usable frame period — see `functions/timing.py` for the
numbers. The frame length is stated from the firmware and the shutter register
instead. The reference scripts `matlab/extract_DCR.m`, `extract_dcr.py` and
`dcr_hitmap.py` still read it, and are wrong by a factor of `nframes`; they are
flagged in place rather than silently corrected.

### Measurement data

No `.bin` is tracked in git or shipped in the release. `*.bin` is gitignored, and
`main.spec` lists the vendor binaries individually rather than bundling the
folder they share with the app's default output path.

## Installation and usage

A fresh, separate virtual environment is highly recommended before installing the package.
This can be done using pip, see, e.g., [this](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/).
This can help to avoid any dependency conflicts and ensure smooth operation of the
package.

First, check if the virtualenv package is installed. To do this, one can run:
```
pip show virtualenv
```
If the package was not found, it can be installed using:
```
pip install virtualenv
```
To create a new environment, run the following:
```
virtualenv PATH/TO/NEW/ENVIRONMENT
```
To activate the environment (on Windows):
```
PATH/TO/NEW/ENVIRONMENT/Scripts/activate
```
and on Linux:
```
source PATH/TO/NEW/ENVIRONMENT/bin/activate
```

Alternatively, to start using the package, one can download the whole repo. "requirements.txt" 
lists all packages required for this project to run. One can create 
an environment for this project either using conda or pip following the instruction 
above. Once the new environmnt is activated, run the following to install 
the required packages:
```
cd PATH/TO/GITHUB/CODES/dapkel-rtp
pip install -r requirements.txt
```
Now, the package can be installed via
```
pip install -e .
```
where '-e' stands for editable: any changes introduced to the package will
instantly become a part of the package and can be used without the need
of reinstalling the whole thing.

For conda users, the new environment can be installed using the 'requirements' 
text file directly:
```
conda create --name NEW_ENVIRONMENT_NAME --file /PATH/TO/requirements.txt -c conda-forge
```
To install the package, first, switch to the created environment:
```
conda activate NEW_ENVIRONMENT_NAME
```
and run
```
pip install -e .
```

## How to contribute

This repo consists of two branches: 'main' serves as the release version
of the package, tested, proven to be functional, and ready to use, while
the 'develop' branch serves as the main hub for testing new stuff. To
contribute, the best way would be to fork the repository and use the 'develop'
branch for new introductions, submitting the results via pull requests. 
Everyone willing to contribute is kindly asked to follow the 
[PEP 8](https://peps.python.org/pep-0008/) and 
[PEP 257](https://peps.python.org/pep-0257/) conventions.

## License and contact info

This package is available under the MIT license. See LICENSE for more information. If you'd like to contact me, the author, feel free to write at sergei.kulkov23@gmail.com.
