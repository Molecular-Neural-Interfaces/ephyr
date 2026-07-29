# Analysis

## Usage of the Labeled Data

After you annotate an experiment in Ephyr, you can load the same `*_ephyr` folder from Python and work
with signals, sessions, events, periods, and add-on outputs.

You can also generate a starter script from the GUI (**Add-ons → Generate script**). The example below
follows the same API and extends it with reading spike detection results from disk.

### Main objects

| Object | Role |
|--------|------|
| `EphyrSessionManager` | Entry point: load an experiment folder, switch sessions, access `experiment_data` and `user_session` |
| `ExperimentData` | `header` plus `data_memmaps[sweep_idx][channel_idx]` and voltage conversion helpers |
| `Header` | Sample rate, sweep/channel counts, channel names, units, ranges, and source provenance |
| `UserSession` | Events, periods, vocabularies, experiment description, and `gui_setup` |
| `GuiSetup` | View state: current sweep/window, channel groups, filters, visibility flags, add-on toggles |
| `events_table` | Convenience view of events with names and overlapping period names |

#### `Header` (high level)

- Provenance: `type_before_conversion`, `name_before_conversion`, creation date/time before conversion
- Timing: `sample_interval_microseconds`, `sample_rate`
- Shape: `number_of_channels`, `number_of_sweeps`, `number_of_points_per_sweep`
- `channel_info`: per-channel `name`, `probe`, `units`, analog/digital min/max, prefiltering, points, impedance

#### `UserSession` / `GuiSetup` (high level)

- Labels: `events`, `events_vocabulary`, `periods`, `periods_vocabulary`
- Text: `experiment_description`
- View: `gui_setup` (`current_sweep_idx`, `start_point`, `duration_ms`, `channels_groups`, `channels_setup`, …)
- `events_table` rows: `name`, `sweep_idx`, `time_ms`, `is_bad`, `periods` (list of period names)

### Example script

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

# Work with spikes (Spike detection add-on results under add_ons/data)
# Each result directory contains files named "{sweep_idx}.spikes.json" (SpikesPayload).
spikes_root = Path(OUT_EPHYR_FOLDER) / "add_ons" / "data" / "spike_detection"
if spikes_root.exists():
    for result_dir in spikes_root.iterdir():
        if not result_dir.is_dir():
            continue
        for spikes_path in sorted(result_dir.glob("*.spikes.json")):
            payload = json.loads(spikes_path.read_text(encoding="utf-8"))
            sweep_idx = payload["sweep_idx"]
            for ch_idx, spikes in payload["spikes_by_channel"].items():
                print("Sweep", sweep_idx, "channel", ch_idx, "spikes:", spikes)
```

### Spike payload shape

Spike utils (Spike detection) write JSON files that match the `SpikesPayload` model. Important fields:

| Field | Meaning |
|-------|---------|
| `sweep_idx` | Sweep the detection was run on |
| `sample_rate` | Sample rate used during detection |
| `detector_name`, `threshold`, polarity flags, merge window, ignore rules | Detection parameters |
| `spikes_by_channel` | Map of channel index → list of spikes |
| Each spike | `time_ms`, `value`, `polarity`, optional `sample_idx` |

Reading with the standard library `json` module keeps analysis scripts independent of the add-on package.
Add-on authors can instead use `SpikesPayload` / `read_spikes_payload` from the Spike utils shared helpers.

### Notes

- Indexing for memmaps is `[sweep_idx][channel_idx]`, then a sample slice.
- `from_int16_to_voltage_val` scales using the channel’s analog/digital range and units (results in µV-oriented values used by the GUI pipeline).
- `session.user_session` and `session.current_user_session` refer to the active session after `switch_sessions` / `new_user_session`.
- Run analysis scripts in the same Python environment where `ephyr` is installed (`pip install ephyr`).
