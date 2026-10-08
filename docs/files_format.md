# Files Format

## Supported source files

Two options are available for opening data in Ephyr: **File → Open File** and **File → Open Folder**. 
Select **Open File** to specify a source file, or **Open Folder** to specify a folder, depending on the format. 
Ephyr determines the format, converts it to an Ephyr experiment folder when required, and then opens a session.



| Format | Typical extensions / markers | How to open |
|--------|------------------------------|-------------|
| Axon ABF | `.abf` | Select the **file** |
| EDF | `.edf` | Select the **file** |
| DAQ | `.daq` | Select the **file** |
| XDAT | `.xdat`, `*.xdat.json` | Select the **file** |
| NWB | `.nwb` | Select the **file** |
| Multi Channel Systems | exported `.raw` / `.mcsraw`, DataManager `.h5` / `.hdf5`, CMOS-MEA `.cmcr` / `.cmtr` | Select the **file**. Native `.mcd` files are not supported; export them to MCS RAW with a binary header or MCS HDF5 first. A `.cmtr` file references its source `.cmcr` through an HDF5 external link, so both files must remain together. |
| Neuralynx | `.ncs` (also `.nev`, related text) | Prefer the **folder** that contains `.ncs` files. Selecting a Neuralynx file is also accepted; Ephyr resolves to the parent folder of the `.ncs` set. |
| Open Ephys | session folder (`settings.xml`, continuous streams, etc.) | Select the **session folder**, or a file inside it (Ephyr walks parent directories until a valid session is found). |
| Intan RHD | `.rhd`, optional `.xml` | Select the **folder** that contains the `.rhd` files, or an `.rhd`/`.xml` file (resolved to the parent folder). |
| Intan RHS | `.rhs`, optional `.xml` | Same as RHD: prefer the **folder** with `.rhs` files. |
| WEEGIT | paired `*.lfp` + `*.header.json` | Select the **`.lfp` file**; Ephyr picks up `<name>.header.json` next to it. |
| Existing Ephyr experiment | `header.json` inside `*_ephyr` | Select the **Ephyr experiment folder** directly (no conversion). |

### Conversion notes

- When you open a non-Ephyr source, Ephyr creates a sibling folder named `{stem}_ephyr` next to the selected path. 
For example, `exp.abf` becomes `exp_ephyr`, and the folder `my_rec` becomes `my_rec_ephyr`.
- For Intan recordings, the conversion dialog may offer the option **Group all Intan files into one sweep.**
- Ephyr reads Multi Channel Systems files directly. For HDF5 files that contain multiple analog streams, `stream_id` (or `mcs_stream_id`) can be supplied as a reader option. 
CMOS-MEA sensor regions are flattened into channels named by ROI and sensor coordinates. 
CMOS files that contain only detected spikes and no continuous stream cannot be converted to Ephyr traces.
- If a valid `{stem}_ephyr` folder already exists next to the source, Ephyr loads it instead of converting the source again.
- **NWB** conversion requires a regular `TimeSeries` or `ElectricalSeries` with a usable sample rate, 
typically under `acquisition` or `processing`. Files containing only spike-sorted `Units` and no continuous 
voltage series are not supported for conversion. For large HD-MEA NWB files, quantization occurs without a full-file peak scan; 
conversion still streams the entire series once into `data/`.

After conversion, electrode order and, for NWB, spatial layout can be restored from the original source. 
Use **Channels layout → Import from source** and **Layout settings → Import from source**. 
(see [Settings Panel](gui/settings_panel.md#channel-layout)).

## Ephyr files

After conversion (or when you open an existing experiment), Ephyr uses this directory layout:

```text
$EXPERIMENT_ephyr/
├── header.json
├── data/
│   ├── sweep_0/
│   │   ├── channel_0.samples
│   │   ├── channel_1.samples
│   │   └── ...
│   └── sweep_1/
│       └── ...
├── sessions/
│   └── $SESSION_NAME.json
└── add_ons/
    └── data/
        ├── $ADD_ON_MODULE_NAME/
        └── ephyr/
```

### `header.json`

This file identifies a valid Ephyr experiment folder. The experiment metadata file contains the sample rate or interval, 
number of channels and sweeps, points per sweep, channel names, units, analog and digital ranges, provenance of the original source, 
and related fields. 


### `data/`

Signal samples stored as read-only **int16** memory-mapped files.

- Each sweep is stored in its own subdirectory: `sweep_0`, `sweep_1`, and so on. Numbering is 0-based; 
a recording with 101 sweeps uses `sweep_0` through `sweep_100`. The GUI sweep control is 1-based, 
so `sweep_0` is displayed as sweep 1.
- Inside each sweep directory, there is one `*.samples` file per channel, such as `channel_0.samples` 
and `channel_1.samples`. These files are indexed by channel index using the same 0-based numbering.

Scripts and the GUI read these arrays through `ExperimentData.data_memmaps` and convert them to voltage 
with `from_int16_to_voltage_val` (see [Using Labeled Data](analysis/labeled_data.md)).

### `sessions/`

Each session is stored as a JSON file (for example, `my_session.json`) that contains:

- event and period vocabularies and placements
- experiment description text
- GUI setup, including the visible window, channel groups, filters, add-on toggles, 
layer visibility (such as traces, channel names, events, and periods), and related view state

The file is created when you create or save a session. You can switch between sessions without reloading the signal data.

### `add_ons/` and `add_ons/data/`

Persistent storage for add-ons:

- `add_ons/data/$ADD_ON_MODULE_NAME/` — results and parameters for a specific add-on module, such as spike detection payloads.
- `add_ons/data/ephyr/` —  shared Ephyr-side add-on state, such as preprocessing pipelines used by tools. 

Conversion creates the `add_ons/` directory tree. Individual module folders appear when add-ons run and write data.