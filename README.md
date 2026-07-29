# Ephyr

[![PyPI](https://img.shields.io/pypi/v/ephyr?color=blue)](https://pypi.org/project/ephyr/)
[![Downloads](https://static.pepy.tech/badge/ephyr)](https://pepy.tech/project/ephyr)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/ephyr)](https://pypi.org/project/ephyr/)

## Introduction

**Ephyr** is a cross-platform desktop application for viewing and labeling electrophysiology data
(EEG, patch-clamp, multielectrode recordings, and similar signals).  
It supports Windows, macOS, and Linux.

Ephyr stores data in its own folder layout:

```text
$EXPERIMENT_ephyr
├── header.json
├── data
│   ├── sweep_00000
│   │   ├── 0.wsd
│   │   ├── ...
├── sessions
│   ├── $SESSION_NAME.json
├── add_ons
│   ├── data
│   │   ├── $ADD_ON_MODULE_NAME
```

## Run GUI

```bash
ephyr
```

## Main Features

- Open and switch Ephyr experiments/sessions.
- View traces with per-group and per-channel configuration.
- Navigate time windows and sweeps.
- Add, remove, and label events and periods.
- Manage event/period vocabularies (name + color).
- Apply channel-group filters (low/high/band-pass, notch, etc.).
- Install/update/uninstall add-ons and run runnable add-ons.
- Export screenshots to PNG/SVG (save to file or copy to clipboard).

## Right Panel Forms

### Signal Settings

**Time Settings**
- `Current sweep`
- `Start point index`
- `Duration (ms)`
- `Time step (ms)`
- `Auto-scroll interval (ms)`
- `Number of dots`

**Channel Management**
- `Channels mapping image`:
  - `Attach link`
  - `Attach file`
- `Create channel group`
- `Set units` (opens channel units dialog)

**Per Channel Group**
- `Name`
- `View`
- `Group height ratio`
- `Number to show` (for non-auxiliary groups)
- `Auxiliary channels`
- `Group filters`:
  - filter selector
  - filter params (`Cutoff`, `Low cut`, `High cut`, `Order`, `Ripple`, `Notch`, `Q factor`, `Enabled`)
  - `Disable all`
- Group common style (for non-auxiliary groups):
  - `Scale`
  - `Y offset`
  - `Color`
- Group actions:
  - `Reorder`
  - `Enable all`
  - `Disable all`
  - `Move selected to` + target group + `Move`
- Per channel row:
  - enabled checkbox
  - channel label
  - `Info` field (for example, channel area)
  - for auxiliary groups: per-channel `Scale`, `Y`, `Color`

### Information

- One large text field: `Experiment description`.

### Logs

- Real-time app logs list.
- `Filter` by log level: `ALL`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.
- `Clear` button.

### Add-ons

For each add-on module:
- `View` checkbox
- `Transform` checkbox
- `Run` button

## Popup Dialogs and Fields

### File and Session

- `Convert to Ephyr`:
  - detected source type
  - for RHS: optional `Group all RHS files into one sweep`
  - conversion confirmation
- `Session Name`:
  - `Enter unique session name`
- `Select session`:
  - sessions list
  - `OK/Cancel`

### Labeling and Vocabulary

- `Events` dialog (event vocabulary manager):
  - table columns: `ID`, `Name`, `Color`, `Num in sweep`, `Num in sweeps`
  - buttons: `Add`, `Remove`, `Select`
  - rename in-place by editing `Name`
  - color pick on `Color` double-click
- `Periods` dialog (period vocabulary manager):
  - table columns: `ID`, `Name`, `Color`
  - buttons: `Add`, `Remove`, `Select`
  - rename in-place by editing `Name`
  - color pick on `Color` double-click

### Channel Configuration

- `Header units management`:
  - table: `Index`, `Channel`, `Units`
  - bulk action: `Selected rows unit` + `Set`
  - buttons: `Save changes`, `Cancel`
- `Reorder channels`:
  - drag-and-drop list
  - manual input format: `1,10,12,14-18,20`
  - `Reorder`, `Cancel`
- Channels mapping preview:
  - opens image preview for attached mapping image.

### Add-ons

- `Add-ons` (index manager):
  - left list with install state + name
  - metadata on right: `Module name`, `Version`, `Description`, `Author`, `Keywords`, `Links`
  - actions: `Install/Uninstall`, `Update`
- `Create add-on template` (`Add-ons > Create`):
  - `[project] name`
  - `[project] description`
  - `authors` rows (`name`, `email`)
  - feature flags: `viewable`, `transformation`, `runnable`
  - output is generated to `./add_on_development`
- `Generate Python script` (`Add-ons > Generate script`):
  - `Ephyr folder`
  - `Session name`
  - `Output script`
  - `Include events block`
  - `Include periods block`

### Export

- `Screenshot options`:
  - `Image format` (`png` / `svg`)
  - `Copy to clipboard` or `Save as file`

## Developers

### Convert source data to Ephyr format

```python
from pathlib import Path
from ephyr.converter.ephyr_io import EphyrIO

path_to_parent = Path("/path/to/parent/dir")
exp_name = "20252222"
exp_dir = path_to_parent / exp_name
out_ephyr_folder = path_to_parent / f"{exp_name}_ephyr"

for progress in EphyrIO.convert_from_source_to_ephyr(exp_dir):
    print(f"\rProgress: {progress}%", end="", flush=True)

print("Created:", out_ephyr_folder)
```

Supported import formats include old Ephyr and Intan RHS (XDAQ).

### Create add-ons from GUI

1. Open Ephyr.
2. Go to `Add-ons > Create`.
3. Fill:
   - project metadata (`name`, `description`, `authors`)
   - capability flags (`viewable`, `transformation`, `runnable`)
4. Click `Generate template`.
5. Implement add-on logic in generated `add_on_development/example.py`.
6. Add metadata/entry point in generated `add_on_development/pyproject.toml`.

### Generate a script with current Ephyr API

1. Go to `Add-ons > Generate script`.
2. Fill:
   - `Ephyr folder` (`*_ephyr`)
   - `Session name` (without `.json`)
   - output `.py` file path
   - optional blocks (`events`, `periods`)
3. Run generated script with the same Python environment where Ephyr is installed.

Generated script demonstrates:
- loading experiment data through `EphyrSessionManager`
- reading raw channel slices from `data_memmaps[sweep_idx][channel_idx]`
- conversion to voltage values via `from_int16_to_voltage_val(...)`
- loading a GUI session via `UserSession.session_name_to_filename(...)`
- iterating events through `session.user_session.events_table`
- iterating periods through `session.user_session.periods`

## License

The code and data files in this distribution are licensed under the terms of
GNU General Public License v3, as published by the Free Software Foundation.  
See [GNU licenses](https://www.gnu.org/licenses/).
