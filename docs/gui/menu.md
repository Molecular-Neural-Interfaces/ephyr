# Menu

The menu bar provides the main application actions. Items that require an open session are enabled after
you load an experiment.

## File

### Open

Opens a dialog titled **Select experiment folder or source file**. Choose either:

- a supported source file or recording folder (Ephyr converts it to a `*_ephyr` experiment), or
- an existing Ephyr experiment folder that already contains `header.json`.

See [Files Format](../files_format.md) for supported formats and how to select them.

### Open Recent

Lists recently opened Ephyr experiment folders. Selecting an entry reloads that experiment.
Missing folders are removed from the list automatically.

### Session

#### New

Creates a new annotation session inside the current experiment. You are prompted for a unique session name.
The new session gets default channel groups and GUI setup and becomes the active session.

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

Quits the application. If the current session has unsaved changes, Ephyr asks for confirmation.
Closing the window uses the same unsaved-changes check.

## Edit

### Export Canvas

Exports the current signal view as PNG or SVG, the same action as **Export Canvas** in the header bar.

### Undo

Reverses the last undoable labeling command (for example adding or removing events/periods or vocabulary changes).

### Redo

Re-applies the last undone command.

## View

### Data Panel

Checkable items that show or hide layers on the signal panel (and related navigator elements):

| Item | Purpose |
|------|---------|
| **Channel Traces** | Show or hide waveform traces. |
| **Channel names** | Show or hide channel name labels drawn on each channel cell. |
| **Events** | Show or hide event markers. |
| **Periods** | Show or hide period intervals and labels. |

These toggles stay in sync with the current session’s GUI setup.

### Session Panel

Checkable items that show or hide sections of the right-hand settings panel:

| Item                      | Panel section |
|---------------------------|----------------|
| **Timeline Settings**     | Sweep and visible time-window controls |
| **Channel Management**    | Channel groups, layouts, filters, and units |
| **Add-ons**               | Searchable add-on list with View / Transform / Run |
| **Recording Description** | Free-text notes and, in Expert mode, visual attachment |
| **Application Logs**      | Live application log and level filter |

If no tool sections are visible, the right panel may hide automatically. Use **Show session panel** in the header bar
to show or hide the whole right panel.

## Events

### Manage

Opens the events vocabulary dialog: visibility, event IDs, names, colors, and counts in the current sweep /
across sweeps. You can show or hide individual event types, add or remove vocabulary entries, rename names
in place, and pick colors. The **Add** button is enabled when a type is selected: it places you in
interactive mode so you can click on the signal to add an event at that time. Right-click or **Esc** cancels.

### Remove in Range

Two-click range that deletes events inside the range. Right-click or **Esc** cancels.

### Set Bad

Interactive two-click range on the signal: events inside the range are marked as bad.
Right-click or **Esc** cancels.

### Unset Bad

Two-click range that clears the bad flag on events inside the range.

## Periods

### Manage

Opens the periods vocabulary dialog: visibility, period IDs, names, and colors. You can show or hide
individual period types and use the same editing patterns as events (add/remove, rename, color pick).
The **Add** button is enabled when a type is selected: click twice on the signal to set the start and end
(can span sweeps). Right-click or **Esc** cancels.

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
