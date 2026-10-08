# Getting Started

**Ephyr** is a cross-platform desktop application for viewing and labeling electrophysiology data 
(EEG, patch-clamp, multielectrode, and similar signals) on Windows, macOS, and Linux. It offers a 
lightweight yet powerful environment for multimodal annotation, with an adaptive interface and performance 
scaling for stable real-time operation under load. EphyR is open-source, Python-based, providing a flexible 
API for post-annotation data access and an add-on architecture that extends functionality without core-code modification.

EphyR addresses file-format diversity through a unified conversion pipeline supporting ABF, EDF, Intan RHD/RHS, Neuralynx, 
Open Ephys, XDAT, and NWB. Conversion preserves metadata including channel names, sampling rates, units, and electrode 
positions when available. It supports interdisciplinary collaboration and provides a simple starting point for beginners 
and neurobiologists and clinical neurophysiologists.

After installation, launch the app with the `ephyr` command. The About dialog (Help → About) shows the
installed version as `Ephyr v…`.

![Ephyr application overview](source/_static/getting_started/app_overview.png)
## Where to go next

Depending on what you need, continue with one of these sections:

- **[Installation](installation.md)** — install Ephyr from PyPI (or check the status of the `.exe` installer) and start the GUI.
- **[Files Format](files_format.md)** — which source formats Ephyr can open, how to open them (file vs folder), and the layout of a `*_ephyr` experiment folder.
- **[Graphic User Interface](gui/index.md)** — main window layout, menus, signal panel, and settings panel.
- **[Add-ons](add_ons/index.md)** — how Viewable, Runnable, and Transformation add-ons fit into the workflow, how to install and run them, and how to develop your own.
- **[Reading Sources](analysis/sources.md)** — how to convert recordings into `*_ephyr` folders from Python, one at a time or in batches.
- **[Using Labeled Data](analysis/labeled_data.md)** — how to load labeled experiments in Python (`EphyrSessionManager`), read signals, sessions, events, periods, and spike sets.
