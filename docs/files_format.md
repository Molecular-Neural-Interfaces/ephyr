# Files Format

## Supported source files

Use **File → Open** and select either a source file or a folder, depending on the format.
Ephyr detects the format, converts it into a Ephyr experiment folder when needed, then opens a session.

| Format | Typical extensions / markers | How to open |
|--------|------------------------------|-------------|
| Axon ABF | `.abf` | Select the **file** |
| EDF | `.edf` | Select the **file** |
| DAQ | `.daq` | Select the **file** |
| XDAT | `.xdat`, `*.xdat.json` | Select the **file** |
| NWB | `.nwb` | Select the **file** |
| Neuralynx | `.ncs` (also `.nev`, related text) | Prefer the **folder** that contains `.ncs` files. Selecting a Neuralynx file is also accepted; Ephyr resolves to the parent folder of the `.ncs` set. |
| Open Ephys | session folder (`settings.xml`, continuous streams, etc.) | Select the **session folder**, or a file inside it (Ephyr walks parent directories until a valid session is found). |
| Intan RHD | `.rhd`, optional `.xml` | Select the **folder** that contains the `.rhd` files, or an `.rhd`/`.xml` file (resolved to the parent folder). |
| Intan RHS | `.rhs`, optional `.xml` | Same as RHD: prefer the **folder** with `.rhs` files. |
| Legacy Ephyr | paired `*.lfp` + `*.header.json` | Select the **folder** that contains the matching pair. |
| Existing Ephyr experiment | `header.json` inside `*_ephyr` | Select the **Ephyr experiment folder** directly (no conversion). |

### Conversion notes

- Opening a non-Ephyr source creates a sibling folder named `{stem}_ephyr` next to the chosen path
  (for example, `exp.abf` → `exp_ephyr`, folder `my_rec` → `my_rec_ephyr`).
- For Intan recordings, the conversion dialog may offer **Group all Intan files into one sweep**.
- If a valid `{stem}_ephyr` folder already exists next to the source, Ephyr loads it instead of converting again.

## Ephyr files

After conversion (or when you open an existing experiment), Ephyr uses this directory layout:

```text
$EXPERIMENT_ephyr/
├── header.json
├── data/
│   └── sweep_NNNNN/
│       ├── 0.samples
│       ├── 1.samples
│       └── ...
├── sessions/
│   └── $SESSION_NAME.json
└── add_ons/
    └── data/
        ├── $ADD_ON_MODULE_NAME/
        └── ephyr/
```

### `header.json`

Experiment metadata: sample rate / interval, number of channels and sweeps, points per sweep,
channel names, units, analog/digital ranges, provenance of the original source, and related fields.
This file identifies a valid Ephyr experiment folder.

### `data/`

Signal samples stored as read-only **int16** memory-mapped files.

- One subdirectory per sweep: `sweep_00000`, `sweep_00001`, …
- Inside each sweep, one `*.samples` file per channel (`0.samples`, `1.samples`, …), indexed by channel index.

Scripts and the GUI read these arrays through `ExperimentData.data_memmaps` and convert them to voltage
with `from_int16_to_voltage_val` (see [Analysis](analysis.md)).

### `sessions/`

User annotation and GUI state. Each session is a JSON file (for example `my_session.json`) that stores:

- event and period vocabularies and placements
- experiment description text
- GUI setup (visible window, channel groups, filters, add-on toggles, and related view state)

Created when you create or save a session. Switch between sessions without reloading the signal data.

### `add_ons/` and `add_ons/data/`

Persistent storage for add-ons:

- `add_ons/data/$ADD_ON_MODULE_NAME/` — results and parameters for a specific add-on module
  (for example spike detection payloads).
- `add_ons/data/ephyr/` — shared Ephyr-side add-on state (for example preprocessing pipelines used by tools).

Conversion creates the `add_ons/` tree; individual module folders appear when add-ons run and write data.
