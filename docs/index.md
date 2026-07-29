# Getting Started

**Ephyr** is a cross-platform desktop application for viewing and labeling electrophysiology data
(EEG, patch-clamp, multielectrode recordings, and similar signals). It supports Windows, macOS, and Linux.

This application is a lightweight yet powerful environment for multimodal annotation of electrophysiological data.
It combines an adaptive interface with intelligent performance scaling to match your machine’s resources,
ensuring stable real-time operation even under heavy loads.

Fully open-source and built in Python, the platform provides a flexible API for post-annotation data access.
Its add-on architecture lets you extend functionality seamlessly without modifying the core codebase.

After installation, launch the app with the `ephyr` command. The About dialog (Help → About) shows the
installed version as `Ephyr v…`.

![Ephyr application overview](source/_static/getting_started/app_overview.png)

## Where to go next

Depending on what you need, continue with one of these sections:

- **[Installation](installation.md)** — install Ephyr from PyPI (or check the status of the `.exe` installer) and start the GUI.
- **[Files Format](files_format.md)** — which source formats Ephyr can open, how to open them (file vs folder), and the layout of a `*_ephyr` experiment folder.
- **[Graphic User Interface](gui/index.md)** — main window layout, menus, signal panel, and settings panel.
- **[Add-ons](add_ons/index.md)** — how Viewable, Runnable, and Transformation add-ons fit into the workflow, how to install and run them, and how to develop your own.
- **[Analysis](analysis.md)** — how to load labeled experiments in Python (`EphyrSessionManager`), read signals, sessions, events, periods, and spike payloads.
