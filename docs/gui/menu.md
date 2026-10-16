# Menu

The menu bar provides the main application actions. Items that require an open session are enabled after
you open a Record.

## File

### Create Ephyr Workspace…

Pick a parent folder and a name. Ephyr creates `<name>_ephyr` there with an empty `workspace.ephyr`.

### Open Ephyr Workspace

- **File…** — select `workspace.ephyr`.
- **Folder…** — select the workspace folder (any folder inside the workspace also works).

You can also drop a workspace folder or `workspace.ephyr` onto the window. See [Files Format](../files_format.md).

### Recent Workspaces

Lists recently opened workspaces. Selecting an entry reloads that workspace.
Missing folders are removed from the list automatically.

### Add Config / Record / Source

Same as the **+** buttons on the recording navigation panel. **Add Config** imports a recording as a
new Config (or offers to add it as a Record when a matching Config already exists). **Add Record**
checks the recording against the current Config. **Add Source** attaches another file to the open Record.

### Session

#### New

Creates a new annotation session inside the current Record. You are prompted for a unique session name.
The new session gets default channel groups and GUI setup and becomes the active session. Events and
periods found in the original recording (`source_annotations/`) are copied in as a starting set.

#### Save

Saves the current user session to `sessions/<name>/` in the Record folder.
Shortcut: **Ctrl+S** (Windows/Linux) or **Cmd+S** (macOS).

#### Import → Full Session

Imports a session folder into the current Record. If the session name already exists, you can rename it.

#### Import → Events

Imports events and their vocabulary from another session folder, or from a WEEGIT `.mat` events file.
Imported times are stored as Record time (`t_ms`).

#### Import → Periods

Imports periods and their vocabulary from another session folder.

#### Import → Settings from Record…

Copies GUI setup (channel groups, filters, layout, visibility flags, navigation mode) from another
Record of the **same Config**. Vocabularies are merged by name when the checkbox is on (the default).
Segment index and start point stay those of the current Record.

#### Export

Copies the current session folder to a directory you choose.

#### Open in Explorer

Opens the current session folder in the system file manager (Finder / Explorer / equivalent).

#### Other Sessions

Dynamic submenu listing other session folders of the same Record. Selecting one switches the active
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
| **Channel Info** | Show or hide `ChannelSetup.info` on each channel cell. When names are also shown and info is not empty, the two are separated by a vertical bar. |
| **Events** | Show or hide event markers. |
| **Periods** | Show or hide period intervals and labels. |

These toggles stay in sync with the current session’s GUI setup.

### Session Panel

Checkable items that show or hide sections of the right-hand settings panel:

| Item                      | Panel section |
|---------------------------|----------------|
| **Recording Navigation**  | Config / Record / Source, navigation mode, current segment, overlay |
| **Timeline Settings**     | Visible time-window controls |
| **Channel Management**    | Channel groups, layouts, filters, and units |
| **Add-ons**               | Searchable add-on list with View / Transform / Run |
| **Recording Description** | Free-text notes and, in Expert mode, visual attachment |
| **Application Logs**      | Live application log and level filter |

If no tool sections are visible, the right panel may hide automatically. Use **Show session panel** in the header bar
to show or hide the whole right panel.

## Events

### Manage

Opens the events vocabulary dialog: visibility, event IDs, names, colors, and counts in the current segment /
across the Record. You can show or hide individual event types, add or remove vocabulary entries, rename names
in place, and pick colors. The **Add** button is enabled when a type is selected: it places you in
interactive mode so you can click on the signal to add an event at that time. Right-click or **Esc** cancels.

### Remove in Range

Two-click range that deletes events inside the range. Right-click or **Esc** cancels.

### Mark as Invalid

Interactive two-click range on the signal: events inside the range are marked as bad.
Right-click or **Esc** cancels.

### Remove Invalid Mark

Two-click range that clears the bad flag on events inside the range.

## Periods

### Manage

Opens the periods vocabulary dialog: visibility, period IDs, names, and colors. You can show or hide
individual period types and use the same editing patterns as events (add/remove, rename, color pick).
The **Add** button is enabled when a type is selected: click twice on the signal to set the start and end
(can span segments). Right-click or **Esc** cancels.

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
