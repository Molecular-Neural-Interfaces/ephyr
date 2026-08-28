# Add-ons Usage

## Manage installed packages

Open **Add-ons → Manage**.

![Add-on Manage dialog](../source/_static/add_ons/manage_dialog.png)

The dialog loads the remote catalog and shows:

| Area | Purpose |
|------|---------|
| **Left list** | Available packages with install state and name |
| **Details** | Module name, version (remote and installed), author, keywords, links, and description |
| **Install** | Downloads and installs the selected package into the Ephyr environment |
| **Update** | Upgrades an already installed package |
| **Uninstall** | Removes the package and cleans related session toggles / experiment `add_ons/data` for that module |

Use Manage when you want to add tools from the published catalog, keep them up to date, or remove ones
you no longer need. Package sources are published in the
[ephyr-add-ons](https://github.com/Molecular-Neural-Interfaces/ephyr-add-ons) repository.

## Search and run from the side panel

Show the Add-ons section with **View → Tools → Add-ons** (or ensure the right panel is visible via **Panel**).

![Add-ons side panel](../source/_static/add_ons/side_panel.png)

| Control | Purpose |
|---------|---------|
| **Search** | Filters the list by add-on label |
| Groups | Installed distributions and **Development add-ons** (`dev_*` modules loaded from `./add_on_development`) |
| **View** | Enables Viewable drawing when the add-on supports it |
| **Transform** | Enables Transformation in the display pipeline when supported |
| **Run** | Starts a Runnable add-on; progress may appear in a loading dialog |

Typical workflow:

1. Install the package from Manage (or develop locally under `add_on_development`).
2. Open the side panel and find the add-on.
3. Click **Run** if it needs configuration or batch processing.
4. Enable **View** and/or **Transform** so results affect the signal panel while you annotate.

See [Workflow](index.md) for how the three capability types interact with signal data.

## Spike importer

**Spike importer** (part of the **Spike utils** package) brings spikes detected outside Ephyr into the
experiment. **Run** it, pick a WEEGIT `.spk` file, and the spikes are written as a new spike set in
`add_ons/data/spike_sets/`, with the sorting method name and the per-spike clusters from the file
preserved. Spike viewer, Spike navigation, Aligned spikes plot and Raster plot then treat the imported
set exactly like a set produced by Spike detection, and colour the clusters when the file contains
more than one.

The file must match the open experiment: channel numbers, sweep numbers and spike positions are
checked against the converted header, and nothing is written if any of them is out of range. A `.spk`
file whose name differs from the recording name only raises a confirmation.

Full format description and field reference:
[Spike utils README](https://github.com/Molecular-Neural-Interfaces/ephyr-add-ons/tree/main/add-ons/spike-utils).
