# Add-on Development

You can extend Ephyr with custom Transformation, Viewable, and/or Runnable add-ons.

## Generate a template from the GUI

1. Open Ephyr.
2. Choose **Add-ons → Create**.
3. Fill in project metadata (`name`, `description`, authors).
4. Click **Generate template**.

Ephyr writes a scaffold into the local add-ons folder (Add-ons → Manage, bottom left).
Until you choose another folder, that is `./add_on_development` in the working directory:

```text
add_on_development/
├── README.md
├── pyproject.toml
└── ephyr_add_ons/
    └── <project_name>/
        ├── __init__.py
        └── entry_point.py
```

`entry_point.py` is a working example with all three capabilities:

- **Run** opens a dialog for channel groups, channels, a constant offset, and a sine
  (amplitude, frequency, phase).
- **Transform** adds that sine to the selected channels.
- **View** draws the same sine on those channels.

Edit that class for your own tool. Metadata and the `ephyr.add_ons` entry point are
declared in `pyproject.toml`.

## How development add-ons are loaded

On startup (and when the runtime add-on list is refreshed), Ephyr:

1. Loads **installed** packages via the `ephyr.add_ons` entry-point group.
2. Loads **development** modules from the local add-ons folder if it exists
   (Add-ons → Manage; the default is `./add_on_development`). A new folder is used
   after Ephyr is restarted:
      - top-level `*.py` files appear as `dev_<stem>`
      - packages under `ephyr_add_ons/<name>/` (including `entry_point.py` and nested modules) appear as `dev_*` entries

Development add-ons show up in the Add-ons side panel under the development group. You can enable
View / Transform and press **Run** the same way as for installed packages. No separate install step is
required while iterating locally.

## Learn from existing add-ons

Study published packages in the official repository (also checked out as the `devtools/ephyr-add-ons` submodule):

[https://github.com/Molecular-Neural-Interfaces/ephyr-add-ons](https://github.com/Molecular-Neural-Interfaces/ephyr-add-ons)

Reference implementations include:

- **Spike utils** — detection, WEEGIT `.spk` import, viewer, navigation, aligned waveforms, raster
- **Labeling utils** — events detection
- **Signal utils** — preprocessing comparison, PSD, spectrogram
- **LFP utils** — current-source density (CSD) visualization

Use those packages together with the generated template as a starting point for your own tools.
