# Using Labeled Data

After you annotate an experiment in Ephyr, you can load the same `*_ephyr` folder from Python and work
with signals, sessions, events, periods, and add-on outputs. You can also generate a starter script
from the GUI (**Add-ons → Generate script**); it uses the same API as the example at the bottom of this
page.

## Main objects

| Object | Role |
|--------|------|
| `EphyrSessionManager` | Entry point: load an experiment folder, switch sessions, access `experiment_data` and `user_session` |
| `ExperimentData` | `header` plus `data_memmaps[sweep_idx][channel_idx]` and voltage conversion helpers |
| `Header` | Sample rate, sweep/channel counts, channel names, units, ranges, and source provenance |
| `UserSession` | Events, periods, vocabularies, experiment description, and `gui_setup` |
| `GuiSetup` | View state: current sweep/window, channel groups, filters, visibility flags, add-on toggles |
| `events_table` | Convenience view of events with names and overlapping period names |

## Experiment structures

Defined in [`ephyr/core/header.py`](https://github.com/Molecular-Neural-Interfaces/ephyr/blob/main/ephyr/core/header.py)
and stored in `header.json`. They describe the recording itself and never change when you annotate.

### `Header`

| Field | Type | Meaning |
|-------|------|---------|
| `type_before_conversion` | `str` | Source format the experiment was converted from |
| `name_before_conversion` | `str` | Original file or folder name |
| `creation_date_before_conversion` | `str` | Recording date reported by the source |
| `creation_time_before_conversion` | `str` | Recording time reported by the source |
| `sample_interval_microseconds` | `float` | Sampling interval in µs |
| `sample_rate` | `float` | Samples per second |
| `number_of_channels` | `int` | Channel count |
| `number_of_sweeps` | `int` | Sweep count (1 for continuous recordings) |
| `number_of_points_per_sweep` | `List[int]` | Samples in each sweep; length equals `number_of_sweeps` |
| `channel_info` | `ChannelInfo` | Per-channel metadata |

### `ChannelInfo`

Every list is indexed by channel index.

| Field | Type | Meaning |
|-------|------|---------|
| `name` | `List[str]` | Channel names |
| `probe` | `List[str]` | Probe / port label |
| `units` | `List[str]` | Voltage unit per channel (`kV`, `V`, `mV`, `uV`, `nV`, `pV`) |
| `analog_min` / `analog_max` | `List[float]` | Analog range used for int16 → voltage scaling |
| `digital_min` / `digital_max` | `List[int]` | Digital range used for int16 → voltage scaling |
| `prefiltering` | `List[str]` | Hardware filtering description from the source |
| `number_of_points_per_channel` | `List[int]` | Sample count per channel, when the source reports it |
| `impedance_ohm` | `List[Optional[float]]` | Electrode impedance, when the source reports it |

## Session structures

Defined in [`ephyr/core/ephyr_session.py`](https://github.com/Molecular-Neural-Interfaces/ephyr/blob/main/ephyr/core/ephyr_session.py).
One experiment folder can hold several sessions (files under `sessions/`), each with its own labels and
view state.

### `EphyrSessionManager`

| Member | Type | Meaning |
|--------|------|---------|
| `ephyr_experiment_folder` | `Optional[Path]` | Loaded `*_ephyr` folder |
| `experiment_data` | `Optional[ExperimentData]` | Header and signal memmaps |
| `current_user_session` | `Optional[UserSession]` | Active session |
| `user_session` | `UserSession` | Same as `current_user_session`, raises when nothing is loaded |
| `session_is_active` | `bool` | Whether an experiment and a session are loaded |
| `other_session_filenames` | `List[str]` | Session files in the folder besides the active one |

Loading API:

| Call | Purpose |
|------|---------|
| `init_from_folder(folder)` | Load an experiment folder and its default session |
| `switch_sessions(session_filename)` | Load another session of the same experiment |
| `new_user_session(session_filename)` | Create an empty session |
| `save_user_session()` | Write the active session back to `sessions/` |
| `UserSession.session_name_to_filename(name)` | Turn a session name into its file name |

### `ExperimentData`

| Member | Type | Meaning |
|--------|------|---------|
| `header` | `Header` | Header of the experiment |
| `data_memmaps` | `Tuple[Tuple[np.memmap, ...], ...]` | Raw int16 samples, indexed `[sweep_idx][channel_idx]` |
| `from_int16_to_voltage_val(data, channel_idx)` | method | Scale raw samples to voltage using the channel's ranges and units |
| `process_data_pipeline(...)` / `process_single_channel(...)` | methods | The same filtering / decimation pipeline the GUI draws with |

### `UserSession`

| Field | Type | Meaning |
|-------|------|---------|
| `session_filename` | `str` | File name of this session |
| `changes_saved` | `bool` | `False` when the session has unsaved changes |
| `events` | `List[Event]` | Point labels |
| `events_vocabulary` | `Dict[int, EventVocabularyEntry]` | Event names and colors by id |
| `periods` | `List[Period]` | Interval labels |
| `periods_vocabulary` | `Dict[int, PeriodVocabularyEntry]` | Period names and colors by id |
| `experiment_description` | `str` | Free-text notes for the experiment |
| `gui_setup` | `GuiSetup` | View state |
| `events_table` | property | Events joined with their names and the periods they fall into |

Vocabulary helpers: `add_event_vocabulary`, `get_event_vocabulary_name`, `get_event_vocabulary_color`,
`rename_event_vocabulary`, `set_event_vocabulary_color`, `remove_event_vocabulary`, and the matching
`*_period_vocabulary` methods.

### `GuiSetup`

| Field | Type | Meaning |
|-------|------|---------|
| `right_panel_widgets` | `List[RightPanelWidgetEnum]` | Which side-panel widgets are shown |
| `add_ons` | `Dict[str, AddOnSetup]` | Per-add-on view / transform toggles |
| `traces_are_shown` | `bool` | Draw signal traces |
| `channel_names_are_shown` | `bool` | Draw channel names |
| `events_are_shown` | `bool` | Draw events |
| `periods_are_shown` | `bool` | Draw periods |
| `current_sweep_idx` | `int` | Sweep on screen |
| `start_point` | `int` | First sample of the visible window |
| `duration_ms` | `int` | Width of the visible window |
| `time_step_ms` | `int` | Step used by navigation |
| `autoscroll_step_interval_ms` | `int` | Autoscroll timer interval |
| `number_of_dots_to_display` | `int` | Target point count per trace (decimation) |
| `channels_groups` | `List[ChannelGroup]` | Channel groups in display order |
| `channels_setup` | `Dict[int, ChannelSetup]` | Per-channel style |
| `channels_mapping_img` | `str` | Optional electrode mapping image |

### `ChannelGroup`

| Field | Type | Meaning |
|-------|------|---------|
| `channel_indexes` | `List[int]` | Channels of the group, in display order |
| `enabled_indexes` | `Set[int]` | Channels that are actually drawn |
| `filters` | `List[FilterConfig]` | Filter chain applied to the group |
| `name` | `str` | Group title |
| `is_shown` | `bool` | Group visibility |
| `is_auxiliary` | `bool` | Auxiliary group (per-channel style, no windowing) |
| `cut_traces` | `bool` | Clip traces to their cell |
| `group_layout` | `GroupLayout` | Placement of the group on the panel |
| `channels_layout` | `ChannelsLayout` | Grid of channels inside the group |

Helpers: `effective_grid()`, `grid_dims()`, `visible_window()`, `visible_cells()`,
`visible_enabled_channels()`, `visible_channels()`, `clamp_layout()`.

### `ChannelsLayout`

| Field | Type | Meaning |
|-------|------|---------|
| `columns_num` | `int` | Columns in the grid |
| `columns_num_to_show` | `int` | Columns visible at once |
| `cur_column_idx` | `int` | First visible column |
| `rows_num` | `Optional[int]` | Rows in the grid (derived when `None`) |
| `rows_num_to_show` | `int` | Rows visible at once |
| `cur_row_idx` | `int` | First visible row |
| `enable_custom_layout` | `bool` | Use `layout_table` instead of a plain list |
| `draw_borders` | `bool` | Draw cell borders |
| `layout_table` | `Optional[List[List[int]]]` | Channel index per grid cell (`-1` for an empty cell) |

### `GroupLayout`

| Field | Type | Meaning |
|-------|------|---------|
| `layout_row_idx` | `int` | Row of the group on the panel |
| `layout_column_idx` | `int` | Column of the group on the panel |
| `height_ratio` | `float` | Share of the row height |
| `width_ratio` | `float` | Share of the row width |

### `ChannelSetup`

| Field | Type | Meaning |
|-------|------|---------|
| `scale` | `float` | Vertical scale in µV |
| `y_offset` | `float` | Vertical offset |
| `color` | `str` | Trace color |
| `info` | `str` | Free-text note, e.g. the brain area |

### `Event`, `Period`, vocabularies and `EventTableRow`

| Structure | Fields |
|-----------|--------|
| `Event` | `event_name_id: int`, `sweep_idx: int`, `time_ms: float`, `is_bad: bool` |
| `Period` | `period_name_id: int`, `start_sweep_idx: int`, `start_time_ms: float`, `end_sweep_idx: int`, `end_time_ms: float` |
| `EventVocabularyEntry` | `name: str`, `color: str` |
| `PeriodVocabularyEntry` | `name: str`, `color: str` |
| `EventTableRow` | `name: str`, `sweep_idx: int`, `time_ms: float`, `is_bad: bool`, `periods: List[str]` |

### `AddOnSetup`

| Field | Type | Meaning |
|-------|------|---------|
| `view_enabled` | `bool` | Add-on draws on the signal panel |
| `transform_enabled` | `bool` | Add-on transforms the displayed signal |

### `FilterConfig`

`FilterConfig` is a discriminated union on `filter_type`; every filter has `enabled: bool` and
`order: int` besides the fields below.

| `filter_type` | Class | Own fields |
|---------------|-------|------------|
| `butter_lowpass` | `ButterworthLowPassFilter` | `cutoff_hz` |
| `butter_highpass` | `ButterworthHighPassFilter` | `cutoff_hz` |
| `butter_bandpass` | `ButterworthBandPassFilter` | `lowcut_hz`, `highcut_hz` |
| `cheby_bandpass` | `ChebyshevBandPassFilter` | `lowcut_hz`, `highcut_hz`, `ripple_db` |
| `notch` | `NotchFilter` | `notch_freq_hz`, `q_factor` |

## Spike sets written by add-ons

The Spike utils package stores every spike set — detected by **Spike detection** or imported from a
WEEGIT `.spk` file by **Spike importer** — in one shared folder:

```
add_ons/data/spike_sets/{set_name}/spike_set_meta.json
add_ons/data/spike_sets/{set_name}/{sweep_idx}.spikes.json
```

`spike_set_meta.json` (`SpikeSetMeta`):

| Field | Meaning |
|-------|---------|
| `source` | `detected` or `imported` |
| `detector_name` | Detection / sorting method, e.g. `mad`, `adaptive_mad`, `kilosort` |
| `group_key`, `group_name` | Channel group the set was detected on (empty for imported sets) |
| `preprocessing_pipeline`, `threshold`, `adaptive_sigma` | Detection parameters |
| `clusters` | Cluster labels present in the set (`0` means unclustered) |
| `source_file`, `created_at` | Origin of an imported set |

`{sweep_idx}.spikes.json` (`SpikesPayload`):

| Field | Meaning |
|-------|---------|
| `sweep_idx` | Sweep the spikes belong to |
| `sample_rate` | Sample rate the times were computed with |
| `source`, `detector_name`, `threshold`, polarity flags, merge window, ignore rules | How the set was produced |
| `group_key`, `group_name` | Channel group of the set |
| `source_file` | `.spk` file for imported sets |
| `spikes_by_channel` | Map of channel index → list of spikes |

Each spike (`SpikePoint`):

| Field | Meaning |
|-------|---------|
| `sample_idx` | Sample index inside the sweep (may be `null`) |
| `time_ms` | Time inside the sweep |
| `value` | Peak amplitude, negative for downward spikes |
| `polarity` | `negative` or `positive` |
| `cluster` | Sorting label inside the set; `0` means unclustered |

Reading these files with the standard library `json` module keeps analysis scripts independent of the
add-on package. Add-on authors can instead use `SpikesPayload` / `read_spikes_payload` from the Spike
utils shared helpers.

## Example script

```python
import json
from pathlib import Path

from ephyr.core.ephyr_session import EphyrSessionManager, UserSession

# Init session
OUT_EPHYR_FOLDER = Path("/path/to/experiment_ephyr")
session = EphyrSessionManager()
session.init_from_folder(OUT_EPHYR_FOLDER)

# Work with data
print(session.experiment_data.header)
sweep_idx, start_point, end_point = 0, 0, 10_000
for ch_idx in range(session.experiment_data.header.number_of_channels):
    channel_data = session.experiment_data.data_memmaps[sweep_idx][ch_idx][start_point:end_point]
    print(
        f"Channel {session.experiment_data.header.channel_info.name[ch_idx]} max voltage val: ",
        max(session.experiment_data.from_int16_to_voltage_val(channel_data, ch_idx)),
    )

# Work with GUI session
session_filename = UserSession.session_name_to_filename("your_session")
session.switch_sessions(session_filename)
print(session.current_user_session.gui_setup)

# Work with events
for event in session.user_session.events_table:
    # skip events in period
    if "PERIOD_NAME" in event.periods:
        continue
    print(
        f"event={event.name} sweep={event.sweep_idx} "
        f"time_ms={event.time_ms} bad={event.is_bad} periods={event.periods}"
    )

# Work with periods
for period in session.user_session.periods:
    period_name = session.user_session.get_period_vocabulary_name(period.period_name_id)
    print(
        f"period={period_name} "
        f"start=({period.start_sweep_idx}, {period.start_time_ms} ms) "
        f"end=({period.end_sweep_idx}, {period.end_time_ms} ms)"
    )

# Work with spikes (detected and imported sets share one folder)
spike_sets_root = Path(OUT_EPHYR_FOLDER) / "add_ons" / "data" / "spike_sets"
if spike_sets_root.exists():
    for set_dir in sorted(spike_sets_root.iterdir()):
        if not set_dir.is_dir():
            continue
        meta_path = set_dir / "spike_set_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        print(f"spike set={set_dir.name} source={meta.get('source')} clusters={meta.get('clusters')}")
        for spikes_path in sorted(set_dir.glob("*.spikes.json")):
            payload = json.loads(spikes_path.read_text(encoding="utf-8"))
            for ch_idx, spikes in payload["spikes_by_channel"].items():
                print("  sweep", payload["sweep_idx"], "channel", ch_idx, "spikes:", len(spikes))
```

## Notes

- Indexing for memmaps is `[sweep_idx][channel_idx]`, then a sample slice.
- `from_int16_to_voltage_val` scales using the channel’s analog/digital range and units (results in µV-oriented values used by the GUI pipeline).
- `session.user_session` and `session.current_user_session` refer to the active session after `switch_sessions` / `new_user_session`.
- Development add-ons write to `dev_`-prefixed folders, so spike sets of a development build live in `add_ons/data/dev_spike_sets/`.
- Run analysis scripts in the same Python environment where `ephyr` is installed (`pip install ephyr`).
