# Menu

The menu bar provides the main application actions. Items that require an open session are enabled after
you load an experiment.

## File

### Open

Opens a dialog titled **Select experiment folder or source file**. Choose either:

- a supported source file or recording folder (Weegit converts it to a `*_weegit` experiment), or
- an existing Weegit experiment folder that already contains `header.json`.

See [Files Format](../files_format.md) for supported formats and how to select them.

### Open Recent

Lists recently opened Weegit experiment folders. Selecting an entry reloads that experiment.
Missing folders are removed from the list automatically.

### Session

#### New

Creates a new annotation session inside the current experiment. You are prompted for a unique session name.
The new session gets default channel groups and GUI setup and becomes the active session.

#### Save

Saves the current user session to `sessions/<name>.json` in the experiment folder.
Shortcut: **Ctrl+S** (Windows/Linux) or **Cmd+S** (macOS).

#### Import → session

Imports a session JSON file into the current experiment. If the session name already exists, you can rename it.

#### Import → events

Imports events and their vocabulary from another session JSON file, or from a legacy `.mat` events file.
Imported times are validated against the experiment’s sweeps and duration.

#### Import → periods

Imports periods and their vocabulary from another session JSON file.

#### Import → settings

Imports GUI setup (channel groups, time window defaults, visibility flags, and related view settings)
from another session. Sweep index and start point are reset as needed; duration is clamped to valid bounds.

#### Export

Copies the current session JSON file to a directory you choose.

#### Open in Explorer

Opens the current Weegit experiment folder in the system file manager (Finder / Explorer / equivalent).

#### Other Sessions

Dynamic submenu listing other session files in the same experiment. Selecting one switches the active
session without reloading the underlying signal data.

### Exit

Quits the application. If the current session has unsaved changes, Weegit asks for confirmation.
Closing the window uses the same unsaved-changes check.

## Edit

### Undo

Reverses the last undoable labeling command (for example adding or removing events/periods or vocabulary changes).

### Redo

Re-applies the last undone command.

## View

### Signal visibility

Checkable items that show or hide layers on the signal panel (and related navigator elements):

| Item | Purpose |
|------|---------|
| **Traces** | Show or hide waveform traces. |
| **Events** | Show or hide event markers. |
| **Periods** | Show or hide period intervals and labels. |

These toggles stay in sync with the current session’s GUI setup.

### Tools

Checkable items that show or hide sections of the right-hand settings panel:

| Item | Panel section |
|------|----------------|
| **Electrophys trace settings** | Time settings and Channel Management |
| **Information** | Experiment description |
| **Logs** | Application Logs |
| **Add-ons** | Searchable add-on list with View / Transform / Run |

If no tool sections are visible, the right panel may hide automatically. Use **Panel** in the header bar
to show or hide the whole right panel.

## Events

### Show table

Opens the events vocabulary dialog: event IDs, names, colors, and counts in the current sweep / across sweeps.
You can add or remove vocabulary entries, rename names in place, and pick colors.

### Add

Opens the vocabulary dialog so you can select (or create) an event type, then places you in interactive
mode: click on the signal to add an event at that time. Right-click or **Esc** cancels.

### Set bad event

Interactive two-click range on the signal: events inside the range are marked as bad.
Right-click or **Esc** cancels.

### Unset bad event

Two-click range that clears the bad flag on events inside the range.

### Remove

Two-click range that deletes events inside the range.

## Periods

### Show table

Opens the periods vocabulary dialog: period IDs, names, and colors. Same editing patterns as events
(add/remove, rename, color pick).

### Add period

Select a period type from the vocabulary, then click twice on the signal to set the start and end
(can span sweeps). Right-click or **Esc** cancels.

## Add-ons

### Manage

Opens the Add-on Manage dialog to browse the catalog, install, update, uninstall, and inspect package metadata.
See [Add-ons Usage](../add_ons/usage.md).

### Create

Opens the template generator that scaffolds a development add-on under `./add_on_development`.
See [Add-on Development](../add_ons/development.md).

### Generate script

Opens a dialog that writes a starter Python script for loading the current (or selected) Weegit folder
and session via `WeegitSessionManager`. See [Analysis](../analysis.md).

## Help

### About

Shows the application name, version, description, and a link to the documentation site.

### Hotkeys

Lists the built-in keyboard shortcuts:

| Shortcut | Action |
|----------|--------|
| **Ctrl/Cmd + S** | Save current session |
| **Ctrl/Cmd + scroll** | Zoom the visible time window in or out |
| **M** | Cycle the measurement (time/voltage) bar |
| **V** | Select an area for full-view inspection |
| **Esc** | Cancel the current interactive overlay mode |
