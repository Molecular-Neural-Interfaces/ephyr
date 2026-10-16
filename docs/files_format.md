# Files Format

Ephyr keeps converted recordings in a **workspace**: one folder that holds every recording of a study,
grouped by acquisition setup. The original recordings are never modified and are not needed after
conversion.

## Hierarchy

| Level | What it is | Holds |
|-------|------------|-------|
| **Workspace** | A study or project folder `<name>_ephyr`. | Configs. |
| **Config** | One acquisition setup: the same channels, in the same order, at the same sample rate. | Records and the source signatures every Record must match. |
| **Record** | One recording session (one imported file or folder). | Sources, sessions, events, periods, add-on data. |
| **Source** | One signal stream of a Record with its own sample rate and channel set (for example the wideband electrode stream and a 1 kHz analog stream). | Samples, one file per channel. |
| **Segment** | A continuous piece of a source: a sweep, a trigger block, an Open Ephys recording, the part between two gaps of a Neuralynx file. | Position in the samples and its start time. |

Records of one Config share GUI settings: channel groups, filters and layout refer to channels by
index, so they can be copied from one Record to another (**Import → Settings from Record…**).

## Workspace on disk

```text
<name>_ephyr/
├── workspace.ephyr
└── configs/
    └── <config_id>/
        ├── config.ephyr
        └── records/
            └── <record_id>/
                ├── record.ephyr
                ├── sources/
                │   └── <source_id>/
                │       ├── channel_0.samples
                │       ├── channel_1.samples
                │       └── ...
                ├── source_annotations/
                │   ├── events.csv
                │   └── periods.csv
                ├── sessions/
                │   └── <session_name>/
                │       ├── settings.json
                │       ├── events.csv
                │       └── periods.csv
                ├── add_ons/
                │   └── data/
                │       └── <add_on_module_name>/
                └── logs/
```

- Folder ids (`config_id`, `record_id`, `source_id`) are lower-case slugs made from the names you
  enter. Renaming a Config, Record or Source changes only its display name, never the folder.
- The main source of every Record is called `main`. Further sources get ids such as `rate_1000hz`
  or a slug of the stream name.
- The workspace contains no absolute paths, so it can be copied or moved to another computer as is.
- A workspace cannot be created inside another workspace.

### Manifests

All `*.ephyr` files are JSON with a `format` and `format_version` field. Each Workspace, Config and
Record has a random `uid` that does not depend on its name or folder.

| File | Contents |
|------|----------|
| `workspace.ephyr` | Workspace name, `uid`, ordered list of Config ids. |
| `config.ephyr` | Config name, `uid`, `main_source_id`, ordered list of Record ids, and for each source: name, **signature** (`sample_rate`, `dtype`, channel names and units in order) and descriptive fields (`source_format`, `segment_kind`, probes, prefiltering). |
| `record.ephyr` | Record name, `uid`, `start_datetime`, **inputs** (format, root name, content fingerprint, reader options), and for each source: per-channel calibration (`analog_min/max`, `digital_min/max`, impedance), `t_start_ms` and **segments** (`start_sample_idx`, `number_of_samples`, `t_start_ms`, `label`). |

Channel units are part of the Config signature: relabelling units in **Set units** changes them for
every Record of the Config. Calibration lives in the Record, because two recordings of one setup may be
quantized differently.

### Samples

`sources/<source_id>/channel_N.samples` is a raw little-endian **int16** array (`<i2`), one file per
channel, 0-based channel index. All segments of a source are stored back to back in the same file; the
`segments` list in `record.ephyr` says where each one starts. The physical value of a sample is

```text
value = analog_min + (sample - digital_min) * (analog_max - analog_min) / (digital_max - digital_min)
```

in the channel unit from the Config signature.

### Time

Every annotation is stored in **Record time** `t_ms`: milliseconds since the start of the recording,
including the gaps between segments. A segment starts at its `t_start_ms`; sample `i` of a segment is at
`t_start_ms + i * 1000 / sample_rate`. Annotations therefore stay valid whichever source or navigation
mode you look at them in.

### Events and periods

`events.csv`:

| Column | Meaning |
|--------|---------|
| `id` | Unique id inside the file. |
| `t_ms` | Record time in milliseconds. |
| `source_id`, `channel` | Optional: the source and channel the event belongs to; empty for record-wide events. |
| `label` | Name from the session vocabulary. |
| `value` | Optional number (for example an amplitude). |
| `is_bad` | `1` for events marked bad, otherwise `0`. |

`periods.csv` has the same columns, with `start_t_ms` and `end_t_ms` instead of `t_ms` and no `is_bad`.

- `source_annotations/` holds what was found in the original recording: Neuralynx `Events.nev`,
  Open Ephys TTL events, EDF+ annotations, NWB `trials` / `epochs`. It is written once on import.
- `sessions/<name>/events.csv` and `periods.csv` hold the user's own annotations.

### Sessions

A session is one user's view and annotation of a Record. `settings.json` stores the event and period
vocabularies (names, colors, visibility), the recording description and the GUI setup: active source,
navigation mode, visible window, channel groups and layout, filters, add-on toggles and panel layout.
You can switch between sessions without reloading the signal.

### Add-on data

`add_ons/data/<add_on_module_name>/` is created when an add-on stores results or parameters for this
Record (for example spike detection payloads).

## Importing recordings

| Action | Where | Result |
|--------|-------|--------|
| **Create Ephyr Workspace…** | File menu, start page | Pick a parent folder and a name; `<name>_ephyr` is created there. |
| **Open Ephyr Workspace → File…** / **Folder…** | File menu, start page, recent list, drag-and-drop | Select `workspace.ephyr` or the workspace folder (any folder inside the workspace also works). |
| **Add Config** | Navigation panel **+** next to *Config*, start page, drag-and-drop of a recording | A new Config with the recording as its first Record. If an existing Config already has the same signature, Ephyr offers to add the recording there as a Record instead. |
| **Add Record** | **+** next to *Record* | The recording is checked against the current Config before conversion. |
| **Add Source** | **+** next to *Source* | A further file of the same recording becomes an extra source of the open Record. Its channels are not checked against the Config. |
| **Remove** | **−** next to each level | Asks for confirmation and shows the number of Records and sessions and the size on disk. The original recording is not touched. The main source cannot be removed. |
| **Rename** | **✎** next to each level | Changes the display name only. |

Conversion writes into a temporary `*.partial` folder that is moved into place when it is complete, so
a cancelled or failed import leaves nothing behind.

### Duplicates

Each input is identified by a content **fingerprint** that does not depend on where the files are:
for every file of the recording its path inside the recording folder, its size and a SHA-256 of its
first, middle and last MiB; the `digest` combines them. A recording whose digest already exists in the
workspace is refused with a pointer to the Record that holds it. The last known location of the
original recording on this computer is remembered outside the workspace, so that tools such as
**Channels layout → Import from source** can find it again.

### Validation

When a recording is added to a Config, its main source is compared with the Config main source:

| Field | Rule | Effect |
|-------|------|--------|
| Sample rate | Equal within 1e-6 relative | Blocks |
| Number of channels | Equal | Blocks |
| Channel names | Equal and in the same order | Blocks |
| Channel units | Equal after normalization (`uV` = `µV`) | Blocks |
| Sample type | Equal | Blocks |
| Source format, segment kind | Equal | Warning |
| Probe, prefiltering | Equal | Warning |
| Calibration, impedance, number and length of segments, date | Not compared | — |
| Other sources | Not compared | — |

A different channel order means a different Config. On a blocking mismatch Ephyr shows a table of the
differences and offers to create a new Config from the recording instead.

## Supported recordings

Select a file or a folder, depending on the format. Ephyr finds the recording root itself (for example
the folder of a Neuralynx set when you pick one `.ncs` file).

| Format | Select | Sources | Segments | Source annotations |
|--------|--------|---------|----------|--------------------|
| Axon ABF (`.abf`) | file | one | sweeps | — |
| EDF / EDF+ (`.edf`) | file | one per sample rate | one | EDF+ annotations |
| DAQ (`.daq`) | file | one | trigger sweeps | — |
| XDAT (`.xdat`, `*.xdat.json`) | file | one | one | — |
| NWB (`.nwb`) | file | each `ElectricalSeries` / `TimeSeries` | series that differ only in time | `/intervals/trials`, `/intervals/epochs` |
| Multi Channel Systems (`.mcd`, `.raw` / `.mcsraw`, `.h5` / `.hdf5`, `.cmcr` / `.cmtr`) | file | each continuous analog stream | trigger blocks | — |
| Neuralynx (`.ncs`, `Events.nev`) | folder (or any `.ncs` file in it) | one | parts between timestamp gaps | `Events.nev` |
| Open Ephys | session folder (or a file inside it) | one per sample rate | recordings | TTL events |
| Intan RHD / RHS (`.rhd`, `.rhs`) | folder (or a file in it) | one | files, or one joined segment | — |
| WEEGIT (`*.lfp` + `*.header.json`) | the `.lfp` file | one | sweeps | — |

Format notes:

- **Intan:** the import dialog offers **Join Intan files into one continuous segment** (on by default).
- **Multi Channel Systems:** for `.mcd`, continuous analog streams are imported in µV; digital,
  trigger and spike streams are skipped. A `.cmtr` file references its `.cmcr` through an HDF5 external
  link, so both files must stay together. CMOS-MEA sensor regions become channels named by ROI and
  sensor coordinates; files with only detected spikes cannot be imported.
- **NWB:** a regular `TimeSeries` / `ElectricalSeries` with a usable sample rate is required; files
  with only spike-sorted `Units` cannot be imported. Large HD-MEA files are quantized without a full
  peak scan.

After import, electrode order and (for NWB) spatial layout can be restored from the original recording
via **Channels layout → Import from source** and **Layout settings → Import from source**
(see [Settings Panel](gui/settings_panel.md#channel-layout)).
