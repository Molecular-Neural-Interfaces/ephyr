# Files Format

Ephyr keeps converted recordings in a **workspace** — a single folder containing all recordings for a study, 
grouped by acquisition setup. Original recordings are never modified and are no longer required after conversion.

## Hierarchy

| Level | What it is | Holds |
|-------|------------|-------|
| **Workspace** | The top-level study or project folder, named `<name>_ephyr`. | Configs. |
| **Config** | A single acquisition setup: a fixed set of channels, in a fixed order, at a fixed sample rate. | Records, together with the source signatures that every Record must match. |
| **Record** | A single recording session, corresponding to one imported file or folder. | Sources, sessions, events, periods, and add-on data. |
| **Source** | A single signal stream within a Record, with its own sample rate and channel set (for example, the wideband electrode stream and a 1 kHz analog stream). | Samples, stored as one file per channel. |
| **Segment** | A continuous piece of a source: a sweep, a trigger block, an Open Ephys recording, or the interval between two gaps of a Neuralynx file. | Position in the samples and its start time. |

Records within the same Config share GUI settings: channel groups, filters, and layout refer to channels by index, 
so these settings can be copied from one Record to another (**Import → Settings from Record…**).


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

- Folder IDs (`config_id`, `record_id`, `source_id`) are lowercase slugs derived from the names you
  enter. Renaming a Config, Record or Source changes only its display name; the folder name remains unchanged.
- Every Record has a main source with the ID `main`. Additional sources receive IDs such as `rate_1000hz` or a slug of the stream name.
- The workspace contains no absolute paths and can therefore be copied or moved to another computer without modification.
- A workspace cannot be created inside another workspace.

### Manifests

All `*.ephyr` files are JSON files containing with a `format` and `format_version` field. Every Workspace, Config and
Record has a randomly generated `uid` that is independent of its name and folder.

| File | Contents |
|------|----------|
| `workspace.ephyr` | Workspace name, `uid`, and an ordered list of Config IDs. |
| `config.ephyr` | Config name, `uid`, `main_source_id`, an ordered list of Record IDs, and for each source: name, **signature** (`sample_rate`, `dtype`, channel names and units in order) and descriptive fields (`source_format`, `segment_kind`, probes, prefiltering). |
| `record.ephyr` | Record name, `uid`, `start_datetime`, **inputs** (format, root name, content fingerprint, reader options), and for each source: per-channel calibration (`analog_min/max`, `digital_min/max`, impedance), `t_start_ms` and **segments** (`start_sample_idx`, `number_of_samples`, `t_start_ms`, `label`). |

Channel units are part of the Config signature: changing units in **Set units** updates them for every Record in that Config.
Calibration is stored in the Record, since two recordings from the same setup may be quantized differently.

### Samples

`sources/<source_id>/channel_N.samples` is a raw little-endian **int16** array (`<i2`), with one file per
channel, 0-based channel index. All segments of a source are stored consecutively in the same file; the
`segments` list in `record.ephyr` specifies where each segment starts. The physical value of a sample is

```text
value = analog_min + (sample - digital_min) * (analog_max - analog_min) / (digital_max - digital_min)
```

in the channel unit from the Config signature.

### Time

All annotation is stored in **Record time** (`t_ms`): milliseconds since the start of the recording,
including intervals between segments. A segment starts at its `t_start_ms`; sample `i` of a segment occurs at
`t_start_ms + i * 1000 / sample_rate`. Annotations therefore remain valid regardless of the source or navigation 
mode used to view them.

### Events and periods

`events.csv`:

| Column | Meaning |
|--------|---------|
| `id` | Unique ID within the file. |
| `t_ms` | Record time, in milliseconds. |
| `source_id`, `channel` | Optional: the source and channel to which the event belongs; empty for record-wide events. |
| `label` | Name from the session vocabulary. |
| `value` | Optional numeric number (for example an amplitude). |
| `is_bad` | `1` for events marked bad, otherwise `0`. |

`periods.csv` contains the same columns, except that `start_t_ms` and `end_t_ms` replace `t_ms`, and the `is_bad` column is omitted.

- `source_annotations/` contains annotations found in the original recording: Neuralynx `Events.nev`,
  Open Ephys TTL events, EDF+ annotations, NWB `trials` / `epochs`. This directory is written once during import.
- `sessions/<name>/events.csv` and `periods.csv` contain user-created annotations.

### Sessions

A session represents a single user's view and annotation of a Record. `settings.json` stores the event and period
vocabularies (names, colors, visibility), the recording description, and the GUI setup: active source,
navigation mode, visible window, channel groups and layout, filters, add-on toggles, and panel layout.
Sessions can be switched without reloading the signal.

### Add-on data

The `add_ons/data/<add_on_module_name>/` directory is created when an add-on stores results or parameters for this
Record (for example, spike detection payloads).

## Importing recordings

| Action | Where | Result |
|--------|-------|--------|
| **Create Ephyr Workspace…** | File menu, start page | Select a parent folder and enter a name; `<name>_ephyr` is created that folder. |
| **Open Ephyr Workspace → File…** / **Folder…** | File menu, start page, recent list, drag-and-drop | Select `workspace.ephyr` or the workspace folder (any folder whithin the workspace is also accepted). |
| **Add Config** | Navigation panel **+** next to *Config*, start page, drag-and-drop of a recording |  A new Config is created with the recording as its first Record. If an existing Config has the same signature, Ephyr offers to add the recording to that Config as a Record instead. |
| **Add Record** | **+** next to *Record* | The recording is checked against the current Config before conversion. |
| **Add Source** | **+** next to *Source* | A additional file of the same recording becomes an extra source of the open Record. Its channels are not checked against the Config. |
| **Remove** | **−** next to each level | Requests confirmation and displays the number of Records and sessions, as well as the size on disk. The original recording is not modified. The main source cannot be removed. |
| **Rename** | **✎** next to each level | Changes the display name only. |

Conversion writes to a temporary `*.partial` folder, witch is moved into place upon completion; thus,
a cancelled or failed import leaves no residual files.

### Duplicates

Each input is identified by a content **fingerprint** that is independent of file locations.
For each file in the recording, the fingerprint includes its path within the recording folder, its size, 
and a SHA-256 hash of its first, middle, and last MiB; the `digest` combines these values. A recording whose digest already exists in the
workspace is rejected, with a reference to the Record that contains it. The last known location of the
original recording on the local computer is stored outside the workspace, so that tools such as
**Channels layout → Import from source** can locate it again.

### Validation

When a recording is added to a Config, its main source is compared against the Config's main source:

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

A different channel order implies a different Config. On a blocking mismatch Ephyr shows a table of the
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
