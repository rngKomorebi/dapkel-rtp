"""The user guide shown by Help -> User guide, as HTML sections.

Kept apart from the window that shows it ('help.py') so the text can be edited
without reading any Qt. Each section is ``(anchor, title, body)``; the body is
the subset of HTML ``QTextBrowser`` renders, with the colours left out -- the
window adds a stylesheet in the current theme's colours.

Every statement here describes what the code does. When a tab changes, change
its section with it: a guide that disagrees with the window is worse than none.
"""

from __future__ import annotations

# Section anchors the window opens at for each tab, by tab index in
# MainWindow -- so F1 lands on the tab in front.
TAB_ANCHORS = ("single", "chain", "live", "quality")

SECTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "start",
        "Getting started",
        """
<p>DAPKEL-RTP drives the Kelpie v2 SPAD camera: it programs the FPGA, runs
acquisitions into <code>.bin</code> files, previews the sensor live and checks
the data you took. It has four tabs, each covered in its own section:</p>
<ul>
<li><b>Single Acquisition</b>: one program, <i>N</i> files into one folder.</li>
<li><b>Chain Acquisition</b>: a queue of jobs, each with its own program,
frame count and shutter time, run back to back.</li>
<li><b>Live View</b>: a continuously refreshing hitmap, 32&times;32 or a
stitched 64&times;64.</li>
<li><b>Data Quality</b>: decode a <code>.bin</code> and check that the TDC
actually recorded timing.</li>
</ul>

<h3>A typical session</h3>
<ol>
<li>Switch on the camera and set the SPAD bias on the supply. The app cannot
set the bias; it only records the value you type in.</li>
<li>On <b>Single Acquisition</b>, choose the <b>Output Folder</b>.</li>
<li>Choose the <b>Firmware</b> and the <b>Program</b>. Changing either one
runs <b>Power Mgt</b> automatically, which programs the FPGA. Watch the log
for &#10003; and check that the <i>FPGA:</i> label at the right names what you
picked.</li>
<li>Set <b>Frames</b>, <b>#Acq</b> (number of files) and <b>Shutter</b>. The
label beside the firmware shows the frame length and the run's total camera
time, so check it before a long run.</li>
<li>Press <b>Run Acquisition</b>. The progress bar counts files and estimates
the time left, and the log lists every file written.</li>
<li>Open <b>Data Quality</b>, press <b>Rescan</b>, pick the newest file
(<i>Newest first</i> puts it at the top) and press <b>Run Check</b>.</li>
</ol>

<p class="note">Every control also has a tooltip: hover over it to see
one.</p>
""",
    ),
    (
        "concepts",
        "Key concepts",
        """
<h3>Programs</h3>
<p>A program (<code>params/camera/programs/program_*.txt</code>) configures
the SPADs. Its <b>tag</b> is the part after <code>program_</code>, and every
file acquired with it carries that tag in its name. The tag also tells the
analysis what the data means:</p>
<table>
<tr><th>Tag</th><th>Data</th></tr>
<tr><td><code>S0C</code>&ndash;<code>S3C</code></td><td>Photon counts from one
SPAD position of every 2&times;2 macropixel (S0&ndash;S3). Live View's
64&times;64 mode interleaves the four into the full array.</td></tr>
<tr><td><code>S0T</code>&ndash;<code>S3T</code>, <code>C2T</code>&ndash;<code>C4T</code></td>
<td>Timestamps (TDC codes).</td></tr>
<tr><td><code>ORC</code>, <code>ORT</code>, <code>ORS0S1</code>&hellip;</td><td>First
photon / OR of the macropixel.</td></tr>
<tr><td><code>coincS0S1</code>&hellip;</td><td>Coincidences.</td></tr>
</table>
<p>The Chain tab's program boxes group the programs under these headings.</p>

<h3>Firmware</h3>
<p>Two FPGA bitstreams exist, and which one is loaded changes what a frame
is:</p>
<table>
<tr><th>Firmware</th><th>Frame length</th><th>The Shutter box means</th></tr>
<tr><td><code>short_exposure</code></td><td>fixed 9 &micro;s</td><td>how long
the shutter is open <i>inside</i> that frame (50&ndash;500 ns typically,
capped at 9 &micro;s)</td></tr>
<tr><td><code>long_exposure</code></td><td>shutter + 9 &micro;s</td><td>the
open time <i>X</i>, with 9 &micro;s of readout added on top</td></tr>
</table>
<p>Each bitstream lives at
<code>params/camera/&lt;firmware&gt;/bitfile/Kelpie_top.bit</code>. If one is
missing, its entry in the Firmware box says <i>[bitstream missing]</i> and
Power Mgt falls back to the legacy <code>params/camera/bitfile/</code>, saying
so in the log. If you switch firmware while the shutter is above the new
maximum, the shutter is lowered to fit and the log says so.</p>
<h4>Custom firmware</h4>
<p>A bitstream other than the two shipped ones (an external-APD build, a test
build from the FPGA designers) is added from the Firmware box itself: choose
<b>Add custom firmware&hellip;</b> at the bottom of the list, pick the
<code>.bit</code> file, give it a name, and say which timing it follows,
<code>short_exposure</code> (fixed 9&nbsp;&micro;s frame) or
<code>long_exposure</code> (shutter + 9&nbsp;&micro;s). The timing decides
what the Shutter box means and the frame length shown beside it, so ask the
FPGA designers if unsure.</p>
<p>The app copies the file into your own user folder,
<code>%LOCALAPPDATA%&#92;DAPKEL&#92;dapkel-rtp&#92;firmware</code> (the same folder whether you run the exe or the source
code; <b>Open firmware folder&hellip;</b> at the bottom of the Firmware box
shows it in Explorer). Nothing is written next to the exe, so keeping the exe
on the desktop adds no folder there. From then on the firmware is listed in
the Firmware box on Single Acquisition, Chain Acquisition and Live View,
including after a restart, with a newer exe downloaded anywhere, and even if
the original file is moved or deleted. Each Windows user has their own list.
The shipped
<code>short_exposure</code> and <code>long_exposure</code> bitstreams are never
changed, and the downloaded release exe stays the same for everyone else.
Unlike the shipped two, a custom firmware never falls back to the legacy
bitstream: if its copy is gone, Power Mgt stops and says so.</p>
<p>In <code>metadata.json</code>, <code>firmware_version</code> is the timing
(<code>short_exposure</code> or <code>long_exposure</code>, as the analysis
code expects), <code>firmware_name</code> is the name you gave, and
<code>firmware_bitfile_source</code> and <code>firmware_bitfile_sha256</code>
say exactly which file was loaded.</p>
<p><b>Remove custom firmware&hellip;</b> (shown once one has been added)
deletes the app's copy, not the original file. Select a different firmware in
every Firmware box first: one that is still selected cannot be removed.</p>

<h3>Power Mgt and the FPGA state</h3>
<p><b>Power Mgt</b> runs <code>Kelpie_v2_pwr_mgt.exe</code>, which loads the
selected bitstream and program onto the FPGA. It runs on its own whenever the
program or the firmware changes, and you can also press it by hand. Run stays
greyed out until the FPGA holds what is selected.</p>
<p>There is one FPGA and all the tabs share it. The <i>FPGA:</i> label shows
what is <b>actually loaded</b>, not what is selected. If another tab
reprograms the FPGA (for example Live View's 64&times;64 mode, which cycles
through four programs), Single and Chain Acquisition disable Run and ask for
Power Mgt again, so you never acquire with the wrong program loaded. Live View
does not notice: press its Power Mgt after using another tab.</p>

<h3>Frames, blocks and file size</h3>
<ul>
<li>One frame is 2048 bytes (32&times;32 pixels).</li>
<li>The readout hands data over in <b>blocks of 8192 frames (16 MiB)</b>. A
run that is not a whole number of blocks still fills its last block, and the
surplus slots are a byte-exact <b>replay</b> of the slots 8192 earlier. They
are copies, not extra data.</li>
<li>That is why the acquisition tabs only offer whole blocks: 8192, 16&nbsp;384,
32&nbsp;768, 65&nbsp;536, 131&nbsp;072, 262&nbsp;144 and 524&nbsp;288 (each
double the last, 1 to 64 blocks), then <b>1&nbsp;024&nbsp;000 frames</b>
(125 blocks), the most one acquisition can take. The board's DDR3 memory is 2 GiB, which would hold 1&nbsp;048&nbsp;576
frames, but runs above 1&nbsp;024&nbsp;000 do not work. The default is 16&nbsp;384 (two
blocks).</li>
<li>Never infer a frame count from a file size. The Data Quality tab lists
<i>slots</i>, which is a size.</li>
</ul>

<h3>Chip configuration (Settings)</h3>
<p><b>&#9881; Settings</b> on each acquisition tab opens the chip
configuration bits and the folder holding <code>Kelpie_v2.exe</code>. The
ticked bits are combined into the <code>chip_config</code> number shown at
the bottom of the dialog and passed to the exe:</p>
<table>
<tr><th>Bit</th><th>Name</th></tr>
<tr><td>0</td><td>chip_debug</td></tr>
<tr><td>1</td><td>chip_timing (on by default)</td></tr>
<tr><td>2</td><td>chip_artif_rdout</td></tr>
<tr><td>4</td><td>single_shot_noise</td></tr>
<tr><td>5, 6</td><td>memory_select0, memory_select1</td></tr>
<tr><td>7</td><td>debug_last_row</td></tr>
<tr><td>8</td><td>external_frame_trigger: each frame waits for a pulse on
the SMA input. With <i>N</i> frames set, the run only finishes after
<i>N</i> pulses, each more than 9 &micro;s after the last.</td></tr>
</table>
<p><code>clk_shift</code> is listed in the dialog but is not part of
<code>chip_config</code>. Each tab keeps its own Settings.</p>

<h3>Files written</h3>
<ul>
<li>Data files are named
<code>&lt;prefix&gt;_&lt;tag&gt;&lt;number&gt;.bin</code>, for example
<code>data_ORT1.bin</code>, <code>data_ORT2.bin</code>, &hellip;</li>
<li><b>metadata.json</b>: one record per run in the output folder, covering
frame count, shutter, firmware and its bitstream hash, chip config, program,
bias, timestamps and durations. It is first written after the first file
(status <i>running</i>) and updated at the end (<i>completed</i>,
<i>aborted</i> or <i>failed</i>). A <code>metadata.json</code> this app did
not write is never overwritten.</li>
<li><code>frame_rate_cnt.txt</code> is written by the exe. Nothing in the app
reads it, because it is not a usable frame period.</li>
</ul>
""",
    ),
    (
        "single",
        "Single Acquisition",
        """
<p>Runs <code>Kelpie_v2.exe</code> <i>#Acq</i> times with one program,
writing one <code>.bin</code> per run into the output folder.</p>
<table>
<tr><th>Control</th><th>What it does</th></tr>
<tr><td>Output Folder</td><td>Where the files and
<code>metadata.json</code> go. Created if it does not exist. Defaults to
<code>functions/data</code>. Keep the path to plain ASCII characters:
<code>Kelpie_v2.exe</code> receives it in the PC's ANSI code page, so other
characters (Cyrillic, for example) would reach it as <code>?</code>. A run
with such a folder does not start, and the message names the path.</td></tr>
<tr><td>Program</td><td>The SPAD program, listed by file name
(<code>program_ORT.txt</code>, &hellip;). Defaults to <b>ORT</b>. Changing it
runs Power Mgt, which loads the new program onto the FPGA.</td></tr>
<tr><td>Frames</td><td>Frames per file. Only whole 8192-frame readout blocks
are offered: 8192, doubling up to 524&nbsp;288, then 1&nbsp;024&nbsp;000, the
most one acquisition can take. Each option shows in brackets the size of the
file it writes, in whole MB (1&nbsp;MB = 1&nbsp;000&nbsp;000 bytes): 17, 34, 67,
134, 268, 537, 1074 and 2097&nbsp;MB. Windows Explorer shows the same files about
5&ndash;7&nbsp;% smaller, because its &ldquo;MB&rdquo; is 1&nbsp;048&nbsp;576
bytes. Defaults to 16&nbsp;384 (34&nbsp;MB).</td></tr>
<tr><td>#Acq</td><td>How many files to write, 1 to 100&nbsp;000. Defaults to
10.</td></tr>
<tr><td>Shutter / Shutter X</td><td>Shutter time in &micro;s; 0.2 means
200&nbsp;ns. The label and the limit follow the firmware. Under
<code>short_exposure</code> the box reads <i>Shutter</i>: it is how long the
shutter is open inside the fixed 9&nbsp;&micro;s frame, from 0 to
9&nbsp;&micro;s. Under <code>long_exposure</code> it reads <i>Shutter X</i>:
it is the open time X, up to 1&nbsp;s, and the frame lasts X +
9&nbsp;&micro;s.</td></tr>
<tr><td>File</td><td>Filename prefix. Files are named
<code>&lt;prefix&gt;_&lt;tag&gt;&lt;number&gt;.bin</code>, so the default
<code>data</code> with ORT gives <code>data_ORT1.bin</code>,
<code>data_ORT2.bin</code>, &hellip;</td></tr>
<tr><td>Start#</td><td>Number of the first file, default 1. To continue an
interrupted run without overwriting, set it to one past the last file
written.</td></tr>
<tr><td>&#9881; Settings</td><td>Opens this tab's chip configuration: tick
boxes for chip_debug, chip_timing (ticked by default), clk_shift,
chip_artif_rdout, single_shot_noise, memory_select0, memory_select1,
debug_last_row and external_frame_trigger, plus the folder holding
<code>Kelpie_v2.exe</code>. The ticked bits, except clk_shift, are combined
into the <code>chip_config</code> number shown at the bottom of the dialog.
external_frame_trigger makes every frame wait for a pulse on the SMA input,
so leave it off unless a trigger is connected. The other tabs keep their own
separate settings.</td></tr>
<tr><td>Firmware</td><td>Which FPGA bitstream to load.
<code>short_exposure</code>: every frame is a fixed 9&nbsp;&micro;s.
<code>long_exposure</code>: every frame is the shutter time plus
9&nbsp;&micro;s of readout. Changing it runs Power Mgt. If the shutter is
above the new firmware's limit, it is lowered to fit and the log says so. An
entry marked <i>[bitstream missing]</i> loads the legacy bitstream instead,
and the log says so. <b>Add custom firmware&hellip;</b> at the bottom of the list adds another bitstream (a <code>.bit</code> file, for example an external-APD build): you give it a name and say whether it follows short_exposure or long_exposure timing, which decides what the Shutter box means. The app keeps its own copy in your user folder, <code>%LOCALAPPDATA%&#92;DAPKEL&#92;dapkel-rtp&#92;firmware</code>, so the firmware stays in this list after a restart and with a newer exe, even if the original file is moved or deleted, and nothing is added next to the exe. The shipped bitstreams are not changed. <b>Remove custom firmware&hellip;</b> deletes that copy; a firmware that is selected in any Firmware box cannot be removed. <b>Open firmware folder&hellip;</b> shows the folder in Explorer.</td></tr>
<tr><td><i>frame label</i></td><td>Length of one frame and the run's total
camera time (frames &times; #Acq &times; frame length). Check it before a
long run.</td></tr>
<tr><td>Bias</td><td>SPAD bias voltage, <b>for the record only</b>: the app
cannot set it, so set it on the supply. The value is written to
<code>metadata.json</code>. Defaults to 22&nbsp;V; set it to 0 to leave it
blank rather than record a guess.</td></tr>
<tr><td><i>FPGA:</i> label</td><td>What is actually loaded on the FPGA, which
is not always what is selected. All tabs share one FPGA, so if Chain
Acquisition or Live View loads a different program, this tab greys out Run
until you press Power Mgt.</td></tr>
<tr><td>&#9889; Power Mgt</td><td>Runs <code>Kelpie_v2_pwr_mgt.exe</code>,
which loads the selected program and firmware onto the FPGA. It runs on its
own when either one changes. Press it by hand after another tab has
reprogrammed the FPGA. The log shows &#10003; when it succeeds.</td></tr>
<tr><td>&#9654; Run Acquisition</td><td>Starts the run. Greyed out until the
FPGA holds the selected program and firmware; its tooltip says why. The
progress bar counts files and estimates the time left.</td></tr>
<tr><td>&#9632; Abort</td><td>Stops <b>before the next file</b>. The file
being written is finished, and the run is recorded as <i>aborted</i>.</td></tr>
</table>
<p>While a run is going, the Program and Firmware boxes are locked. The log
lists the exact file names that will be written before the run starts.</p>
""",
    ),
    (
        "chain",
        "Chain Acquisition",
        """
<p>A queue of acquisition jobs written into one shared folder, run top to
bottom. Typical use is a DCR measurement: stack S0C, S1C, S2C and S3C jobs and
press Run once. Files are named by program tag, so all of them sit side by
side in the folder.</p>
<h3>Shared settings</h3>
<p>These apply to every job in the chain.</p>
<table>
<tr><th>Control</th><th>What it does</th></tr>
<tr><td>Output Folder</td><td>Where every job's files and
<code>metadata.json</code> go. Created if it does not exist. Defaults to
<code>functions/data</code>. Keep the path to plain ASCII characters:
<code>Kelpie_v2.exe</code> receives it in the PC's ANSI code page, so other
characters (Cyrillic, for example) would reach it as <code>?</code>. A chain
with such a folder does not start, and the message names the path.</td></tr>
<tr><td>Firmware</td><td>Which FPGA bitstream to load.
<code>short_exposure</code>: every frame is a fixed 9&nbsp;&micro;s.
<code>long_exposure</code>: every frame is the shutter time plus
9&nbsp;&micro;s of readout. Changing it runs Power Mgt. If a job's shutter is
above the new firmware's limit, it is lowered to fit and the log says so. An
entry marked <i>[bitstream missing]</i> loads the legacy bitstream instead,
and the log says so. <b>Add custom firmware&hellip;</b> at the bottom of the list adds another bitstream (a <code>.bit</code> file, for example an external-APD build): you give it a name and say whether it follows short_exposure or long_exposure timing, which decides what the Shutter box means. The app keeps its own copy in your user folder, <code>%LOCALAPPDATA%&#92;DAPKEL&#92;dapkel-rtp&#92;firmware</code>, so the firmware stays in this list after a restart and with a newer exe, even if the original file is moved or deleted, and nothing is added next to the exe. The shipped bitstreams are not changed. <b>Remove custom firmware&hellip;</b> deletes that copy; a firmware that is selected in any Firmware box cannot be removed. <b>Open firmware folder&hellip;</b> shows the folder in Explorer.</td></tr>
<tr><td>Bias</td><td>SPAD bias voltage, <b>for the record only</b>: the app
cannot set it, so set it on the supply. The value is written to
<code>metadata.json</code>. Defaults to 22&nbsp;V; set it to 0 to leave it
blank rather than record a guess.</td></tr>
<tr><td>&#9881; Settings</td><td>Opens this tab's chip configuration: tick
boxes for chip_debug, chip_timing (ticked by default), clk_shift,
chip_artif_rdout, single_shot_noise, memory_select0, memory_select1,
debug_last_row and external_frame_trigger, plus the folder holding
<code>Kelpie_v2.exe</code>. The ticked bits, except clk_shift, are combined
into the <code>chip_config</code> number shown at the bottom of the dialog.
external_frame_trigger makes every frame wait for a pulse on the SMA input,
so leave it off unless a trigger is connected. The other tabs keep their own
separate settings.</td></tr>
<tr><td><i>FPGA:</i> label</td><td>What is actually loaded on the FPGA, which
is not always what is selected. All tabs share one FPGA, so if Single
Acquisition or Live View loads a different program, this tab greys out Run
Chain until you press Power Mgt.</td></tr>
</table>
<h3>Each job row</h3>
<table>
<tr><th>Control</th><th>What it does</th></tr>
<tr><td>Program</td><td>This job's SPAD program, grouped under Counting,
Timestamps, First photon / OR and Coincidences. Job #1 defaults to <b>ORT</b>. Changing job
#1's program runs Power Mgt; later jobs are loaded when the chain reaches
them.</td></tr>
<tr><td>Frames</td><td>Frames per file. Only whole 8192-frame readout blocks
are offered: 8192, doubling up to 524&nbsp;288, then 1&nbsp;024&nbsp;000, the
most one acquisition can take. Each option shows in brackets the size of the
file it writes, in whole MB (1&nbsp;MB = 1&nbsp;000&nbsp;000 bytes): 17, 34, 67,
134, 268, 537, 1074 and 2097&nbsp;MB. Windows Explorer shows the same files about
5&ndash;7&nbsp;% smaller, because its &ldquo;MB&rdquo; is 1&nbsp;048&nbsp;576
bytes. Defaults to 16&nbsp;384 (34&nbsp;MB).</td></tr>
<tr><td>Shutter / Shutter X</td><td>This job's shutter time in &micro;s; 0.2
means 200&nbsp;ns. Under <code>short_exposure</code> the box reads
<i>Shutter</i>: it is how long the shutter is open inside the fixed
9&nbsp;&micro;s frame, from 0 to 9&nbsp;&micro;s. Under
<code>long_exposure</code> it reads <i>Shutter X</i>: it is the open time X,
up to 1&nbsp;s, and the frame lasts X + 9&nbsp;&micro;s.</td></tr>
<tr><td><i>frame label</i></td><td>This job's frame length and total camera
time (frames &times; #Files &times; frame length).</td></tr>
<tr><td>#Files</td><td>How many files this job writes, 1 to 100&nbsp;000.
Defaults to 10.</td></tr>
<tr><td>Prefix</td><td>Filename prefix. Files are named
<code>&lt;prefix&gt;_&lt;tag&gt;&lt;number&gt;.bin</code>, so the default
<code>data</code> with ORT gives <code>data_ORT1.bin</code>,
<code>data_ORT2.bin</code>, &hellip;</td></tr>
<tr><td>Start#</td><td>Number of this job's first file, default 1. To continue
an interrupted job without overwriting, set it to one past the last file
written.</td></tr>
<tr><td>&times;</td><td>Removes the job.</td></tr>
</table>
<p><b>+ Add Job</b> appends a job that copies every setting of the last one,
because a chain is usually the same measurement with one thing changed.
Usually you only need to change its program.</p>
<h3>Buttons</h3>
<table>
<tr><th>Control</th><th>What it does</th></tr>
<tr><td>&#9889; Power Mgt</td><td>Runs <code>Kelpie_v2_pwr_mgt.exe</code>,
which loads job #1's program and the selected firmware onto the FPGA. It runs
on its own when either one changes. Press it by hand after another tab has
reprogrammed the FPGA. The log shows &#10003; when it succeeds.</td></tr>
<tr><td>&#9654; Run Chain</td><td>Runs every job, top to bottom. Greyed out
until the FPGA holds job #1's program and the selected firmware; its tooltip
says why.</td></tr>
<tr><td>&#9632; Abort</td><td>Cancels the remaining jobs and stops the current
one <b>before its next file</b>. The file being written is finished.</td></tr>
</table>
<h3>Running</h3>
<ul>
<li>Before each later job, the FPGA is <b>reprogrammed automatically</b> if
that job needs a different program. The log shows each reprogram.</li>
<li>The progress bar spans the whole chain, so its time estimate covers every
job left.</li>
<li>If any job fails, the chain stops there.</li>
<li>The job list cannot be edited while the chain runs.</li>
</ul>
""",
    ),
    (
        "live",
        "Live View",
        """
<p>Runs <code>Kelpie_v2.exe</code> in a loop and shows a <b>hitmap</b> of each
acquisition until you press Stop. Every frame of an acquisition is reduced
into the map; it is not a single-frame snapshot. Each pass writes
<code>live.bin</code> (<code>live_S0C.bin</code> &hellip; <code>live_S3C.bin</code>
in 64&times;64 mode) into the output folder, which defaults to
<code>functions/live</code>. The file is overwritten on every pass, so nothing
piles up. Keep that folder apart from your data.</p>
<table>
<tr><th>Control</th><th>What it does</th></tr>
<tr><td>Mode</td><td><b>32&times;32</b>: the selected program only.
<b>64&times;64</b>: cycles S0C &rarr; S1C &rarr; S2C &rarr; S3C, reprogramming
the FPGA before each, and interleaves the four into the full array. This is
slower, needs all four program files, and leaves the FPGA in an unknown state
for the other tabs.</td></tr>
<tr><td>Output Folder</td><td>Where <code>live.bin</code> is written.
Defaults to <code>functions/live</code>. Keep the path to plain ASCII
characters: <code>Kelpie_v2.exe</code> receives it in the PC's ANSI code
page, so other characters (Cyrillic, for example) would reach it as
<code>?</code>. The live view does not start with such a folder, and the
message names the path.</td></tr>
<tr><td>Program</td><td>The SPAD program, 32&times;32 mode only. Defaults to
<b>ORC</b>. Changing it runs Power Mgt, which loads the new program onto the
FPGA.</td></tr>
<tr><td>Firmware</td><td>Which FPGA bitstream to load.
<code>short_exposure</code>: every frame is a fixed 9&nbsp;&micro;s.
<code>long_exposure</code>: every frame is the shutter time plus
9&nbsp;&micro;s of readout. The frame length is what the rate is divided by.
On this tab, changing the firmware does <b>not</b> run Power Mgt by itself:
press Power Mgt afterwards. If the shutter is above the new firmware's limit,
it is lowered to fit and the status line says so. For a custom firmware the
rate is divided by the frame length of the timing it was added with. <b>Add custom firmware&hellip;</b> at the bottom of the list adds another bitstream (a <code>.bit</code> file, for example an external-APD build): you give it a name and say whether it follows short_exposure or long_exposure timing, which decides what the Shutter box means. The app keeps its own copy in your user folder, <code>%LOCALAPPDATA%&#92;DAPKEL&#92;dapkel-rtp&#92;firmware</code>, so the firmware stays in this list after a restart and with a newer exe, even if the original file is moved or deleted, and nothing is added next to the exe. The shipped bitstreams are not changed. <b>Remove custom firmware&hellip;</b> deletes that copy; a firmware that is selected in any Firmware box cannot be removed. <b>Open firmware folder&hellip;</b> shows the folder in Explorer.</td></tr>
<tr><td>Frames/acq</td><td>Frames per acquisition (per quadrant in
64&times;64), from 1 to 1&nbsp;024&nbsp;000 in any step; the arrows step by
100. Defaults to 1000. More frames give a smoother, more precise map but a
slower refresh. The rate does not change.</td></tr>
<tr><td>Shutter / Shutter X</td><td>Shutter time in &micro;s, default 0.2
(200&nbsp;ns). Under <code>short_exposure</code> the box reads
<i>Shutter</i>: it is how long the shutter is open inside the fixed
9&nbsp;&micro;s frame, from 0 to 9&nbsp;&micro;s. Under
<code>long_exposure</code> it reads <i>Shutter X</i>: it is the open time X,
up to 1&nbsp;s, and the frame lasts X + 9&nbsp;&micro;s.</td></tr>
<tr><td><i>frame label</i></td><td>The frame length the rate divides
by.</td></tr>
<tr><td>&#9881; Settings</td><td>Opens this tab's chip configuration: tick
boxes for chip_debug, chip_timing (ticked by default), clk_shift,
chip_artif_rdout, single_shot_noise, memory_select0, memory_select1,
debug_last_row and external_frame_trigger, plus the folder holding
<code>Kelpie_v2.exe</code>. The ticked bits, except clk_shift, are combined
into the <code>chip_config</code> number shown at the bottom of the dialog.
external_frame_trigger makes every frame wait for a pulse on the SMA input,
so leave it off unless a trigger is connected. The other tabs keep their own
separate settings.</td></tr>
<tr><td>&#9889; Power Mgt</td><td>Runs <code>Kelpie_v2_pwr_mgt.exe</code>,
which loads the selected program and firmware onto the FPGA. In 32&times;32
mode it runs on its own when the program changes. Press it by hand after
changing the firmware, and whenever you come back from a tab that loaded a
different program: Live View does not notice that on its own. It is
greyed out in 64&times;64 mode, which loads its own programs.</td></tr>
<tr><td>&#9654; Start Live View</td><td>Starts the preview loop. In
32&times;32 mode it is greyed out until Power Mgt has loaded the selected
program. In 64&times;64 mode it is always available.</td></tr>
<tr><td>&#9632; Stop</td><td>Ends the preview once the acquisition in
progress finishes.</td></tr>
<tr><td><i>n masked</i></td><td>How many pixels of the map in view are
masked. It sits beside the plot toolbar.</td></tr>
<tr><td>Edit mask&hellip;</td><td>Opens the pixel mask in a window of its own,
which can stay open beside the map while the preview runs. See <i>Masking hot
pixels</i> below.</td></tr>
<tr><td>Reset mask</td><td>Unmasks every pixel of the map in view.</td></tr>
<tr><td>Save mask&hellip;</td><td>Saves the mask of the map in view under a
daughterboard and motherboard. See <i>Saving and loading a mask</i>
below.</td></tr>
<tr><td>Load mask&hellip;</td><td>Replaces the mask of the map in view with
one saved earlier.</td></tr>
</table>
<p>You can change <b>Frames/acq</b> and <b>Shutter</b> while the preview is
running. The change applies to the next acquisition.</p>
<h3>Reading the map</h3>
<ul>
<li>The colour bar is a <b>photon rate</b>: counts divided by frames and by
the frame length. Count programs (<code>*C</code>) read in cps. Timestamp
programs read in Hz: there the map counts frames with a valid timestamp, so
the rate tops out at one firing per frame.</li>
<li>The colour scale spans the full measured range. Hot pixels are shown as
measured; nothing is clipped or smoothed.</li>
<li>The title gives the <b>mean</b>, <b>median</b> and <b>max</b>. The mean is
the steadiest. The median and max jump on short passes, because one photon
is worth 1/(frames &times; shutter).</li>
<li>In timestamp mode the title also gives the <b>peak occupancy</b>: the
fraction of frames the busiest pixel fired in, with its Row/Column. High
occupancy in the beam spot means the shutter is too long for the signal. The
same number on a lone pixel in the dark field is a hot pixel.</li>
<li>Frames that carry no data are dropped. If none did, the status line
warns <i>&ldquo;no frame carried data &mdash; chip idle?&rdquo;</i></li>
<li>A failed acquisition is reported in the status line and retried; it does
not stop the preview.</li>
</ul>
<h3>Masking hot pixels</h3>
<p>A masked pixel is drawn blank with a cross over it, and is left out of
everything read off the map: the colour scale, the mean, median and max in
the title, and the peak occupancy. One hot pixel no longer sets the top of
the colour bar, so the rest of the map gets the full colour range. The status
line says how many masked pixels were left out. A mask takes effect at once,
on the map already shown, also when the preview is stopped.</p>
<ul>
<li><b>Ctrl+click</b> a pixel on the map to mask it. Ctrl+click it again to
unmask it. This does nothing while the toolbar's pan or zoom tool is
selected.</li>
<li><b>Edit mask&hellip;</b> opens a window that lists the masked pixels as
<i>row r, col c</i>, with the count under the list. Type pixels into the box
at the top as <code>row,col</code> entries separated by semicolons, and click
<b>Mask</b> or <b>Unmask</b>; Enter means Mask. Either half of an entry may be
a range: <code>5,12; 30,0-3</code> is pixel (5,&nbsp;12) plus columns 0 to 3
of row 30 (<code>30,0:3</code> works too). Double-click a pixel in the list,
or select several and click <b>Unmask selected</b>, to unmask them.
<b>Clear all</b> unmasks every pixel of the map in view. <b>Close</b> hides
the window and keeps the mask.</li>
<li><b>Reset mask</b> beside the toolbar does the same as <b>Clear
all</b>.</li>
</ul>
<p>Rows and columns are the ones on the plot's axes. 32&times;32 and
64&times;64 mode keep separate masks, because pixel (5,&nbsp;12) is a
different SPAD in each; switching the mode switches the mask shown. The mask
is not remembered when the application closes; save it to use it again.</p>
<h3>Saving and loading a mask</h3>
<ul>
<li><b>Save mask&hellip;</b> asks for the <b>daughterboard</b> and
<b>motherboard</b>, for example <code>D0</code> and <code>M0</code>. A plain
number gets the letter added: typing <code>0</code> in both boxes also gives
D0 and M0. The window shows the file it will write, named after the two
boards: <code>D0_M0.json</code>.</li>
<li>One file holds a 32&times;32 mask and a 64&times;64 mask for the same
boards. Saving writes only the mask of the map in view and keeps the other.
If the file already has a different mask for this map, you are asked before
it is replaced.</li>
<li><b>Load mask&hellip;</b> lists the saved files by name and replaces the
mask of the map in view with the one saved for it. If the file has no mask
for this map (for example only a 32&times;32 one while you are in
64&times;64 mode), a message says so and the mask is left as it was.</li>
<li>The files are kept in your own user folder, <code>%LOCALAPPDATA%&#92;DAPKEL&#92;dapkel-rtp&#92;masks</code>,
whether you run <code>DAPKEL-RTP.exe</code> or the source code. Nothing is
written next to the exe, so a newer exe, wherever it is saved, finds the same
masks. The tooltip on Save mask&hellip; shows the folder. The first time the
app starts with this folder, it copies in any masks saved where earlier
versions kept them (a <code>masks</code> folder next to the exe, or
<code>src/dapkel_rtp/params/masks/</code> from source); the old files are left
where they were, and a file already in the new folder is never
replaced.</li>
<li>The file is plain JSON and can be edited by hand: each pixel is one
<code>[row, col]</code> line under <code>"32x32"</code> or
<code>"64x64"</code>. A pixel outside the map stops the file loading, with a
message naming it.</li>
</ul>
<h3>Zooming and panning</h3>
<ul>
<li><b>Scroll</b> over the map to zoom in or out around the pixel under the
mouse.</li>
<li><b>Drag</b> with the left button to move a zoomed map around.</li>
<li><b>Double-click</b> the map to see the whole map again. The toolbar's
Home button does the same.</li>
</ul>
<p>The zoom stays while the preview refreshes, when the window is resized and
when you stop and start again in the same mode. The toolbar above the plot
still has its own pan and zoom tools, and saves the image.</p>
""",
    ),
    (
        "quality",
        "Data Quality",
        """
<p>Decodes one <code>.bin</code> and shows its TDC-code distribution. It
answers the question worth asking while the camera is still set up: <i>did
the TDC actually record timing?</i> That failure is silent otherwise, because
the decode returns plausible numbers either way.</p>
<table>
<tr><th>Control</th><th>What it does</th></tr>
<tr><td>Data Folder, Browse, &#10227; Rescan</td><td>The folder to list.
Defaults to <code>functions/data</code>, the folder Single and Chain
Acquisition write to by default. Rescan picks up files written since.</td></tr>
<tr><td><i>file list</i></td><td>Every <code>.bin</code> with its slot count,
size, program tag and time. <b>Double-click</b> a file to check it
straight away.</td></tr>
<tr><td>Newest first</td><td>Sorts by modification time, so the file you just
acquired is on top. Untick to sort by name.</td></tr>
<tr><td>Program</td><td><b>Auto</b> reads the tag from the file name. Choose
<i>Timestamp</i> or <i>Count</i> when the name has no tag.</td></tr>
<tr><td>Pixels</td><td><b>All pixels (pooled)</b> is the quickest way to see
whether the run recorded timing at all. <b>Single pixel</b> uses
<b>Row</b>/<b>Col</b> (0&ndash;31).</td></tr>
<tr><td>Frames</td><td>Frames to examine from the start of the file: 8192,
doubling up to 524&nbsp;288, then 1&nbsp;024&nbsp;000, or <b>all</b>. Default
16&nbsp;384. The size in brackets is how much of
the file that reads, in whole MB (1&nbsp;MB = 1&nbsp;000&nbsp;000 bytes). One block (8192) is plenty. <b>all</b> stops where the replayed tail starts, so no frame
is counted twice. If you know the frame count the run was taken with, set it
here.</td></tr>
<tr><td>Bins</td><td>Histogram columns drawn, 8 to 4096, default 256. Only the
drawing is rebinned,
so changing it redraws straight away without decoding again.</td></tr>
<tr><td>&#9654; Run Check / &#9632; Abort</td><td>Start or stop the
check.</td></tr>
</table>
<h3>The report</h3>
<p>Six lines: the file and program; frames examined and how many carried data;
the number of valid codes and of unique codes; the spread (median, 1&ndash;99%
range, most common code); how many pixels recorded timing; and the
<b>verdict</b> with its reason. The coloured left border follows the
verdict.</p>
<table>
<tr><th>Verdict</th><th>When</th></tr>
<tr><td><b>FAIL</b></td><td>no frame carried data; no valid timestamp at
all; codes collapsed onto 4 values or fewer; or one code holds over 90% of
the total (a stuck TDC)</td></tr>
<tr><td><b>SUSPECT</b></td><td>fewer than 16 distinct codes; one code over
50%; or the central 98% spans under 128 codes. A pulsed source at a fixed
delay can legitimately land here.</td></tr>
<tr><td><b>PASS</b></td><td>none of the above</td></tr>
<tr><td><b>n/a</b></td><td>a count (<code>*C</code>) file, where the bits are
photon counts rather than time; a file with no tag in its name and Program on
Auto; or fewer than 100 valid codes</td></tr>
</table>
<p>The verdict is a heuristic, so judge from the numbers printed with it.</p>
<h3>The plots</h3>
<p>Left: the histogram of TDC codes. Healthy timing spreads over the
oscillator range (about 0&ndash;1300); a dead TDC piles onto a few values.
Right: valid timestamps per pixel, which shows whether the timing came from the
whole array or from a corner.</p>
""",
    ),
    (
        "appearance",
        "Themes and preferences",
        """
<ul>
<li><b>View &rarr; Theme</b> switches between eleven presets: the dark ones
first (<b>Deep Space</b>, the default, then Cyberpunk, Midnight, Night wave,
Blueprint, High contrast), then the light ones (Daylight, Komorebi, Earth,
Solarized, Publication). Use a light theme for a bright room or for figures
going into a document.</li>
<li><b>View &rarr; Preferences&hellip;</b> (Ctrl+,) changes any colour of the
window and the plots. Click a colour to pick a new one:
<ul>
<li><b>Interface</b>: window background, panels (tab bar, log, file lists),
input fields, buttons, borders, text, secondary text (field labels, check
boxes, the log), muted text (group-box titles, disabled controls) and the
accent (selected tab, focus ring, progress fill, Run buttons), plus the
interface font size. The font size is on <i>Auto</i> by default, which grows
the text on a tall window.</li>
<li><b>Status</b>: OK (a PASS verdict), Warning (Abort and Stop, a SUSPECT
verdict) and Error (a FAIL verdict).</li>
<li><b>Plots</b>: figure and plot backgrounds, ticks and labels, axes frame,
grid colour, the Data Quality histogram, the hitmap colormap, the plot font
size and whether the grid is shown.</li>
</ul>
Hover shades and button fills follow the colours they belong to, so changing
the window, button, accent or warning colour keeps them matching.</li>
<li>Every change applies at once, to the window and to plots already drawn,
so you can keep Preferences open beside the plot. Choosing a preset clears
your individual changes. <b>Reset to defaults</b> goes back to Deep
Space.</li>
<li>Settings are saved per Windows user.</li>
</ul>
""",
    ),
    (
        "trouble",
        "Troubleshooting",
        """
<table>
<tr><th>Symptom</th><th>What to do</th></tr>
<tr><td>Run is greyed out</td><td>The FPGA does not hold the selected program
and firmware. Press Power Mgt, or wait for the automatic one, and check the
log for &#10003;. The tooltip on Run says why it is disabled.</td></tr>
<tr><td>&ldquo;The FPGA was reprogrammed on another tab&rdquo;</td><td>Another
tab (often Live View's 64&times;64 mode) loaded a different program. Press
Power Mgt again.</td></tr>
<tr><td><code>Kelpie_v2.exe not found</code></td><td>Point &#9881; Settings
&rarr; <i>Kelpie_v2.exe Directory</i> at the folder that holds it.</td></tr>
<tr><td>Firmware shows <i>[bitstream missing]</i></td><td>Put
<code>Kelpie_top.bit</code> in
<code>params/camera/&lt;firmware&gt;/bitfile/</code>. Until then the legacy
bitstream is loaded, and the log and metadata say so.</td></tr>
<tr><td>A custom firmware is no longer in the Firmware box</td><td>Its folder
inside <code>%LOCALAPPDATA%&#92;DAPKEL&#92;dapkel-rtp&#92;firmware</code> was moved or deleted, or is missing
<code>firmware.json</code>. Choose <b>Add custom firmware&hellip;</b> and add
the <code>.bit</code> again. The list is per Windows user: someone logged in
as a different user has their own, and adds the firmware themselves.</td></tr>
<tr><td>A run stopped part-way</td><td>Set <b>Start#</b> to one past the last
file written and run again. Nothing is overwritten.</td></tr>
<tr><td>Live View: &ldquo;no frame carried data&rdquo;</td><td>The chip
produced nothing. Check power and bias, the chip bits (for example
external_frame_trigger waiting for pulses that never come), and that Power Mgt
succeeded.</td></tr>
<tr><td>Data Quality says <b>n/a</b></td><td>Count (<code>*C</code>) files
carry no timing; check a <code>*T</code> acquisition. If the file name has no
tag, set Program to Timestamp.</td></tr>
<tr><td>Text too small or too large</td><td>Preferences &rarr; Interface
&rarr; Font size.</td></tr>
</table>
""",
    ),
    (
        "keys",
        "Menus and shortcuts",
        """
<table>
<tr><th>Item</th><th>Shortcut</th></tr>
<tr><td>Help &rarr; User guide (opens at the tab in front)</td><td>F1</td></tr>
<tr><td>View &rarr; Preferences&hellip;</td><td>Ctrl+,</td></tr>
<tr><td>Data Quality: check a file</td><td>double-click it</td></tr>
<tr><td>Live View: mask or unmask a pixel</td><td>Ctrl+click it on the
map</td></tr>
<tr><td>Live View: zoom in or out</td><td>scroll over the map</td></tr>
<tr><td>Live View: move a zoomed map</td><td>drag it</td></tr>
<tr><td>Live View: whole map again</td><td>double-click the map</td></tr>
<tr><td>Live View mask window: mask the pixels typed</td><td>Enter</td></tr>
</table>
<p>The plot toolbars (Live View, Data Quality) are matplotlib's: Home resets
the view, the arrows step through zoom history, the cross pans, the
magnifier zooms to a rectangle, and the disk saves the figure.</p>
""",
    ),
)
