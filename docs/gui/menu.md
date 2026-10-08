# Menu

The menu bar provides the primary application actions. Menu items that require an open 
session are enabled after you load an experiment.


## File

### Open File

Opens a dialog for selecting a source file. Choose a supported source file. Ephyr converts it to a `*_ephyr` experiment. 

### Open Folder
Opens a dialog for selecting a folder. Choose either:

- a supported recording folder. Ephyr converts it to a `*_ephyr` experiment;
- an existing Ephyr experiment folder that already contains `header.json`.

See [Files Format](../files_format.md) for supported formats and selection instructions.

### Open Recent

Lists recently opened Ephyr experiment folders. Selecting an entry reloads that experiment. 
Missing folders are removed from the list automatically.

### Session

#### New

Creates a new annotation session inside the current experiment. You are prompted for a unique session name. 
The new session receives default channel groups and GUI setup, and becomes the active session. 

#### Save

Saves the current user session to `sessions/<name>.json` in the experiment folder.
Shortcut: **Ctrl+S** (Windows/Linux) or **Cmd+S** (macOS).

#### Import → Full Session

Imports a session JSON file into the current experiment. If the session name already exists, you can rename it.

#### Import → Events

Imports events and their vocabulary from another session JSON file, or from a WEEGIT `.mat` events file.
Imported times are validated against the experiment’s sweeps and duration.

#### Import → Periods

Imports periods and their vocabulary from another session JSON file.

#### Import → Settings

Imports GUI setup (channel groups, time window defaults, visibility flags, and related view settings)
from another session. Sweep index and start point are reset as needed; duration is clamped to valid bounds.

#### Export

Copies the current session JSON file to a directory you choose.

#### Open in Explorer

Opens the current Ephyr experiment folder in the system file manager (Finder / Explorer / equivalent).

#### Other Sessions

Dynamic submenu listing other session files in the same experiment. Selecting one switches the active
session without reloading the underlying signal data.

### Exit

Terminates the application. If the current session has unsaved changes, Ephyr requests confirmation. 
Closing the window applies the same unsaved-changes check.


## Edit

### Export Canvas

Exports the current signal view as PNG or SVG. This command is equivalent to **Export Canvas** in the Toolbar Panel.

### Undo

Reverses the last undoable labeling command, such as adding or removing events or periods, or changing the vocabulary.

### Redo

Re-applies the last undone command.


## View

### Data visibility

Checkable items that control the visibility of layers on the data panel and related navigator elements:

| Item | Purpose |
|------|---------|
| **Channel Traces** | Show or hide waveform traces. |
| **Channel names** | Show or hide channel name labels drawn on each channel cell. |
| **Events** | Show or hide event markers. |
| **Periods** | Show or hide period intervals and labels. |

These toggles stay in sync with the current session’s GUI setup.

### Session Panel visibility

Checkable items that show or hide sections of the right-hand session panel:

| Item | Panel section |
|------|----------------|
| **Recording Navigation** | Current sweep, sweep info, and overlay of other sweeps  |
| **Time settings** | Visible time-window controls |
| **Channel management** | Channel groups, layouts, filters, and units |
| **Add-ons** | Searchable add-on list with View / Transform / Run |
| **Experiment description** | Free-text notes and, in Expert mode, visual attachment |
| **Application logs** | Live application log and level filter |

If no tool sections are visible, the right panel may hide automatically. Use **Show session panel** in the header bar 
to show or hide the entire right-hand settings panel.

## Events

### Manage

Opens the events vocabulary dialog, which displays visibility, event IDs, names, colors, and counts for the current sweep and across sweeps. 
You can show or hide individual event types, create or remove vocabulary entries, rename entries in place, and select colors. The **Add** button is 
enabled when a type is selected: it places you in interactive mode so you can click on the signal to add an event at that time. Right-click or **Esc** cancels.

### Remove in range

Defines a two-click range that deletes events within the range. Right-click or **Esc** cancels.

### Set Bad

Defines an interactive two-click range on the signal; events within the range are marked as bad.
Right-click or **Esc** cancels.

### Unset Bad

Defines an interactive two-click range on the signal; clears the bad flag on events within the range.


## Periods

### Manage

Opens the periods vocabulary dialog, which displays visibility, period IDs, names, and colors. You can show or hide individual 
period types and use the same editing patterns as for events: add or remove entries, rename entries in place, and select colors.
The **Add** button is enabled when a type is selected: click twice on the signal to set the start and end (can span sweeps). 
Right-click or **Esc** cancels.



## Add-ons

### Manage

Opens the Add-on Manage dialog to browse the catalog, install, update, uninstall, and inspect package metadata.
See [Add-ons Usage](../add_ons/usage.md).

### Create

Opens the template generator that scaffolds a development add-on under `./add_on_development`.
See [Add-on Development](../add_ons/development.md).

## Help

### Guide

Opens the Ephyr guide at [https://ephyr.readthedocs.io/en/latest/](https://ephyr.readthedocs.io/en/latest/).

### About

Shows the application name, version, and description.

### Hotkeys

Lists the built-in keyboard shortcuts:

| Shortcut | Action |
|----------|--------|
| **Ctrl/Cmd + S** | Save current session |
| **Ctrl/Cmd + scroll** | Zoom the visible time window in or out |
| **M** | Cycle the scalebar (time/voltage) |
| **V** | Select an area (**Select area**) |
| **Esc** | Cancel the current interactive overlay mode |
| **Right-click** | Cancel the current interactive overlay mode |
