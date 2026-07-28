# Add-on Development

You can extend Weegit with custom Transformation, Viewable, and/or Runnable add-ons.

## Generate a template from the GUI

1. Open Weegit.
2. Choose **Add-ons → Create**.
3. Fill in project metadata (`name`, `description`, authors) and capability flags
   (`viewable`, `transformation`, `runnable`).
4. Click **Generate template**.

Weegit writes a scaffold under the current working directory:

```text
add_on_development/
├── README.md
├── pyproject.toml
└── weegit_add_ons/
    └── <project_name>/
        ├── __init__.py
        └── entry_point.py
```

Implement your logic in `entry_point.py` (a subclass of `BaseAddOn`). Metadata and the
`weegit.add_ons` entry point are declared in `pyproject.toml`.

## How development add-ons are loaded

On startup (and when the runtime add-on list is refreshed), Weegit:

1. Loads **installed** packages via the `weegit.add_ons` entry-point group.
2. Loads **development** modules from `./add_on_development` if that folder exists:
      - top-level `*.py` files appear as `dev_<stem>`
      - packages under `weegit_add_ons/<name>/` (including `entry_point.py` and nested modules) appear as `dev_*` entries

Development add-ons show up in the Add-ons side panel under the development group. You can enable
View / Transform and press **Run** the same way as for installed packages. No separate install step is
required while iterating locally.

## Learn from existing add-ons

Study published packages in the official repository:

[https://github.com/misisisim/weegit-add-ons](https://github.com/misisisim/weegit-add-ons)

In this repository, reference implementations also live under `devtools/add_on_examples/`, including:

- **Spike utils** — detection, viewer, navigation, aligned waveforms, raster
- **Labeling utils** — events detection
- **Signal utils** — preprocessing comparison, PSD, spectrogram
- **LFP utils** — current-source density (CSD) visualization

Use those examples together with the generated template as a starting point for your own tools.

## Related tools

**Add-ons → Generate script** creates a Python script that loads a Weegit folder and session through
`WeegitSessionManager`. That path is aimed at post-annotation analysis rather than GUI add-ons; see
[Analysis](../analysis.md).
