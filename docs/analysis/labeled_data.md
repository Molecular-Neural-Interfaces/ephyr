# Using Labeled Data

After you annotate a Record in Ephyr, you can load the same workspace from Python and work with
signals, sessions, events, periods, and add-on outputs. The example at the bottom of this page
shows the same API. Folder layout is described in [Files Format](../files_format.md).

## Main objects

| Object | Role |
|--------|------|
| `Workspace` | Open a `<name>_ephyr` folder, list Configs and Records |
| `EphyrSessionManager` | Open a Record, switch sessions and sources, access `record_data` and `user_session` |
| `RecordData` | `source_view` plus `memmaps[channel_idx]` (all segments of the active source, concatenated) |
| `SourceView` | Sample rate, channels, physical segments, display segments, Record time ↔ local time |
| `UserSession` | Events, periods, vocabularies, recording description, and `gui_setup` |
| `GuiSetup` | View state: active source, navigation mode, visible window, channel groups, filters |
| `events_table` | Convenience view of events with names, Record time, and overlapping period names |

## Workspace structures

Defined in [`ephyr/core/manifests.py`](https://github.com/Molecular-Neural-Interfaces/ephyr/blob/main/ephyr/core/manifests.py)
and stored in `workspace.ephyr`, `config.ephyr` and `record.ephyr`. They describe the recording itself
and never change when you annotate.

### `ConfigManifest`

| Field | Meaning |
|-------|---------|
| `config_id`, `name`, `uid` | Folder id, display name, random id |
| `main_source_id` | Source every Record of this Config is checked against |
| `sources` | `SourceSpec`: signature (`sample_rate`, `dtype`, channel names and units) and descriptive fields |
| `records` | Ordered list of Record ids |

### `RecordManifest`

| Field | Meaning |
|-------|---------|
| `record_id`, `name`, `uid` | Folder id, display name, random id |
| `start_datetime` | Recording start reported by the source |
| `inputs` | Original recordings: format, root name, content fingerprint, reader options |
| `sources` | `RecordSource`: per-channel calibration, `t_start_ms`, and **segments** |

A segment is `{start_sample_idx, number_of_samples, t_start_ms, label}`. Sample `i` of a segment is at
Record time `t_start_ms + i * 1000 / sample_rate`.

### `SourceView`

Built from the Config source spec and the Record source of the active stream.

| Member | Meaning |
|--------|---------|
| `source_id`, `source_name`, `source_format` | Identity of the stream |
| `sample_rate`, `number_of_channels` | Sampling and channel count |
| `channel_info` | Names, units, probes, analog/digital ranges, impedance |
| `physical_segments` | Segments stored on disk |
| `display_segments` | What the GUI currently shows (one continuous range, each physical segment, or one window around each period of a label) |
| `local_ms_of_time(segment_idx, t_ms)` / `time_of_local_ms(...)` | Record time ↔ position inside a display segment |
| `gap_positions_ms(segment_idx)` | Interruptions inside a concatenated display segment |

## Session structures

Defined in [`ephyr/core/ephyr_session.py`](https://github.com/Molecular-Neural-Interfaces/ephyr/blob/main/ephyr/core/ephyr_session.py).
One Record can hold several sessions (folders under `sessions/`), each with its own labels and view state.

### `EphyrSessionManager`

| Member | Type | Meaning |
|--------|------|---------|
| `workspace` | `Optional[Workspace]` | Open workspace |
| `config` / `record` | manifests | Current Config and Record |
| `record_dir` | `Optional[Path]` | Folder of the open Record |
| `record_data` | `Optional[RecordData]` | Active source samples |
| `source_view` | `Optional[SourceView]` | Metadata of the active source |
| `current_user_session` | `Optional[UserSession]` | Active session |
| `user_session` | `UserSession` | Same as `current_user_session`, raises when nothing is loaded |
| `session_is_active` | `bool` | A Record and a session are loaded |
| `other_session_names` | `List[str]` | Session folders of the Record besides the active one |
| `add_ons_data_folder` | `Path` | `add_ons/data/` of the Record |

Loading API:

| Call | Purpose |
|------|---------|
| `open_record(workspace, config_id, record_id)` | Load a Record of a workspace (no session yet) |
| `new_user_session(session_name)` | Create an empty session; source annotations become its starting events and periods |
| `switch_sessions(session_name)` | Load another session of the same Record |
| `save_user_session()` | Write the active session back to `sessions/<name>/` |
| `load_source` / `switch_source(source_id)` | Change the active source |

### `RecordData`

| Member | Type | Meaning |
|--------|------|---------|
| `source_view` | `SourceView` | Active source |
| `memmaps` | `Tuple[np.memmap, ...]` | Raw int16 samples, indexed `[channel_idx]`, all segments concatenated |
| `from_int16_to_physical(data, channel_idx)` | method | Scale raw samples to physical values in the channel unit |
| `process_data_pipeline(..., segment_idx, ...)` | method | The same filtering / decimation pipeline the GUI draws with |
| `process_data_pipeline_multi_segment(..., segment_indexes, ...)` | method | Same pipeline for several display segments at once |

A slice of samples of a physical segment starts at `source_view.physical_segments[i].start_sample_idx`.

### `UserSession`

| Field | Type | Meaning |
|-------|------|---------|
| `session_name` | `str` | Folder name of this session |
| `changes_saved` | `bool` | `False` when the session has unsaved changes |
| `events` | `List[Event]` | Point labels in Record time |
| `events_vocabulary` | `Dict[int, EventVocabularyEntry]` | Event names and colors by id |
| `periods` | `List[Period]` | Interval labels in Record time |
| `periods_vocabulary` | `Dict[int, PeriodVocabularyEntry]` | Period names and colors by id |
| `experiment_description` | `str` | Free-text recording description |
| `gui_setup` | `GuiSetup` | View state |
| `events_table` | method | Events joined with their names, optional segment, and the periods they fall into |

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
| `channel_infos_are_shown` | `bool` | Draw `ChannelSetup.info` on each channel cell |
| `events_are_shown` | `bool` | Draw events |
| `periods_are_shown` | `bool` | Draw periods |
| `active_source_id` | `Optional[str]` | Source on screen |
| `navigation_mode` | `NavigationModeEnum` | `continuous`, `segment`, or `period_label` |
| `period_label_id` | `Optional[int]` | Period vocabulary used in `period_label` mode |
| `pre_ms` / `post_ms` | `float` | Window around each period in `period_label` mode |
| `current_segment_idx` | `int` | Display segment on screen |
| `overlay_segment_idxs` | `List[int]` | Other display segments drawn in gray (empty = overlay off) |
| `start_point` | `int` | First sample of the visible window inside the display segment |
| `duration_ms` | `int` | Width of the visible window |
| `time_step_ms` | `int` | Timebar step in milliseconds. In Beginner mode the GUI sets this to half of `duration_ms`. |
| `autoscroll_step_interval_ms` | `int` | How often auto-scroll advances, in milliseconds. New sessions default to 1000. |
| `number_of_dots_to_display` | `int` | Target point count per trace (decimation) |
| `channels_groups` | `List[ChannelGroup]` | Channel groups in display order |
| `channels_setup` | `Dict[int, ChannelSetup]` | Per-channel style of the active source |
| `other_sources_setup` | `Dict[str, SourceGuiSetup]` | Channel groups of inactive sources |
| `visual_attachment` | `str` | Optional visual attachment (image URL or embedded file) |

`transferable_copy` copies this setup onto another Record of the same Config. Positions inside the
data (`current_segment_idx`, `overlay_segment_idxs`, `start_point`) stay those of the target Record.

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
| `layout_row_idx` | `int` | Row of the group on the panel. Groups with the same row are placed side by side. |
| `layout_column_idx` | `int` | Position of the group within that row. |
| `height_ratio` | `int` | Relative height of the row. The row uses the maximum height ratio among its groups. |
| `width_ratio` | `int` | Relative width of the group among the groups that share its row. |

Unoccupied cells are not reserved: space is packed along the row. A group that is the only one in its row takes the full width. Two groups in the top row and one group in the row below means the lower group spans the whole row.

### `ChannelSetup`

| Field | Type | Meaning |
|-------|------|---------|
| `scale` | `float` | Full cell-height amplitude, in the channel's unit |
| `y_offset` | `float` | Vertical offset |
| `color` | `str` | Trace color |
| `info` | `str` | Free-text note, e.g. the brain area |

### `Event`, `Period`, vocabularies and `EventTableRow`

| Structure | Fields |
|-----------|--------|
| `Event` | `id: int`, `event_name_id: int`, `t_ms: float`, `is_bad: bool`, optional `source_id`, `channel`, `value` |
| `Period` | `id: int`, `period_name_id: int`, `start_t_ms: float`, `end_t_ms: float`, optional `source_id`, `channel`, `value` |
| `EventVocabularyEntry` | `name: str`, `color: str`, `is_visible: bool` |
| `PeriodVocabularyEntry` | `name: str`, `color: str`, `is_visible: bool` |
| `EventTableRow` | `name: str`, `t_ms: float`, `segment_idx: Optional[int]`, `time_in_segment_ms: Optional[float]`, `is_bad: bool`, `periods: List[str]` |

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

The Spike utils package (distributed separately) stores every spike set — detected by **Spike detection**
or imported from a WEEGIT `.spk` file by **Spike importer** — in one shared folder of the Record:

```
add_ons/data/spike_sets/{set_name}/spike_set_meta.json
add_ons/data/spike_sets/{set_name}/{segment_idx}.spikes.json
```

Files are named by the segment index used at write time (the current display segment for detection,
a physical segment for `.spk` import). Older `{n}.spikes.json` payloads that still have `sweep_idx`
are accepted and rewritten as `segment_idx` on load.

`spike_set_meta.json` (`SpikeSetMeta`):

| Field | Meaning |
|-------|---------|
| `source` | `detected` or `imported` |
| `detector_name` | Detection / sorting method, e.g. `mad`, `adaptive_mad`, `kilosort` |
| `group_key`, `group_name` | Channel group the set was detected on (empty for imported sets) |
| `preprocessing_pipeline`, `threshold`, `adaptive_sigma` | Detection parameters |
| `clusters` | Cluster labels present in the set (`0` means unclustered) |
| `source_file`, `created_at` | Origin of an imported set |

`{segment_idx}.spikes.json` (`SpikesPayload`):

| Field | Meaning |
|-------|---------|
| `segment_idx` | Segment the spikes belong to |
| `sample_rate` | Sample rate the times were computed with |
| `source`, `detector_name`, `threshold`, polarity flags, merge window, ignore rules | How the set was produced |
| `group_key`, `group_name` | Channel group of the set |
| `source_file` | `.spk` file for imported sets |
| `spikes_by_channel` | Map of channel index → list of spikes |

Each spike (`SpikePoint`):

| Field | Meaning |
|-------|---------|
| `sample_idx` | Sample index inside the segment (may be `null`) |
| `time_ms` | Time inside the segment |
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

from ephyr.core.ephyr_session import EphyrSessionManager
from ephyr.core.workspace import Workspace

workspace = Workspace.open(Path("/path/to/study_ephyr"))
config = workspace.configs()[0]
record = workspace.records(config.config_id)[0]

session = EphyrSessionManager()
session.open_record(workspace, config.config_id, record.record_id)
session.switch_sessions(session.other_session_names[0])

view = session.source_view
print(view.source_name, view.sample_rate, view.number_of_channels)

start, n = view.physical_segments[0].start_sample_idx, min(10_000, view.physical_segments[0].number_of_samples)
for ch_idx in range(view.number_of_channels):
    channel_data = session.record_data.memmaps[ch_idx][start:start + n]
    print(
        f"Channel {view.channel_info.name[ch_idx]} max value: ",
        max(session.record_data.from_int16_to_physical(channel_data, ch_idx)),
        view.channel_unit_label(ch_idx),
    )

print(session.user_session.gui_setup)

for event in session.user_session.events_table(view):
    if "PERIOD_NAME" in event.periods:
        continue
    print(f"event={event.name} t_ms={event.t_ms} bad={event.is_bad} periods={event.periods}")

for period in session.user_session.periods:
    period_name = session.user_session.get_period_vocabulary_name(period.period_name_id)
    print(f"period={period_name} start={period.start_t_ms} ms end={period.end_t_ms} ms")

spike_sets_root = session.add_ons_data_folder / "spike_sets"
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
                print("  file", spikes_path.name, "channel", ch_idx, "spikes:", len(spikes))
```

## Notes

- Indexing for memmaps is `[channel_idx]`, then a sample slice over the concatenated source.
  Physical-segment bounds come from `source_view.physical_segments`.
- `from_int16_to_physical` scales using the channel’s analog/digital range only: values are in the
  channel unit (for example `uV`, `mV`, `pA`), exactly as the GUI pipeline draws them.
- `session.user_session` and `session.current_user_session` refer to the active session after
  `switch_sessions` / `new_user_session`.
- Development add-ons write to `dev_`-prefixed folders, so spike sets of a development build live in
  `add_ons/data/dev_spike_sets/`.
- Run analysis scripts in the same Python environment where `ephyr` is installed (`pip install ephyr`).
