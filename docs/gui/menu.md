# Menu

The menu bar provides access to the main application actions. Items that require an open session become enabled once 
a Record is opened.

## File

### Create Ephyr Workspace…

Select a parent folder and enter a name. Ephyr then creates `<name>_ephyr` in that folder with an empty `workspace.ephyr` file.

### Open Ephyr Workspace

- **File…** — select `workspace.ephyr`.
- **Folder…** — select the workspace folder (any folder within the workspace is also accepted).

You can also drag and drop a workspace folder or `workspace.ephyr` onto the window. See [Files Format](../files_format.md).

### Recent Workspaces

Lists recently opened workspaces. Selecting an entry reloads that workspace.
Missing folders are removed from the list automatically.

### Add Config / Record / Source

These actions are equivalent to the **+** buttons in the recording navigation panel. **Add Config** imports a recording as a
new Config (or offers to add it as a Record when a matching Config already exists). **Add Record**
checks the recording against the current Config. **Add Source** attaches additional file to the open Record.

### Session

#### New

Creates a new annotation session within the current Record. You are prompted to enter a unique session name.
The new session receives default channel groups and GUI setup and becomes the active session. Events and
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
Record of the **same Config**. Vocabularies are merged by name when the checkbox is enabled (the default).
The segment index and start point remain those of the current Record.

#### Export

Copies the current session folder to a directory you choose.

#### Open in Explorer

Opens the current session folder in the system file manager (Finder / Explorer / equivalent).

#### Other Sessions

A dynamic submenu listing other session folders of the same Record. Selecting one switches the active
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
| **Channel Traces** | Shows or hides waveform traces. |
| **Channel names** | Shows or hides channel name labels drawn on each channel cell. |
| **Channel Info** | Shows or hides `ChannelSetup.info` in each channel cell. When names are also shown and info field is not empty, the two are separated by a vertical bar. |
| **Events** | Shows or hides event markers. |
| **Periods** | Shows or hides period intervals and labels. |

These toggles remain synchronized with the current session’s GUI setup.

### Session Panel visibility

Checkable items that control the visibility of sections in the right-hand Session panel:

| Item                      | Panel section |
|---------------------------|----------------|
| **Recording Navigation**  | Config / Record / Source, navigation mode, current segment, overlay |
| **Timeline Settings**     | Visible time-window controls |
| **Channel Management**    | Channel groups, layouts, filters, and units |
| **Add-ons**               | Searchable add-on list with View / Transform / Run |
| **Recording Description** | Free-text notes and, in Expert mode, visual attachments |
| **Application Logs**      | Live application log and level filter |

If no sections are visible, the right panel may collapse automatically. Use **Show session panel** in the header bar 
to toggle the entire right-hand Session panel.


## Events

### Manage

Opens the events vocabulary dialog, which displays visibility, event IDs, names, colors, and counts for the current sweep and across sweeps. 
You can show or hide individual event types, create or remove vocabulary entries, rename entries in place, and select colors. The **Add** button is 
enabled when a type is selected: enters interactive mode, in which you can click on the signal to add an event at that time. Right-click or **Esc** cancels.

### Remove in range

Defines a two-click range on the signal; events within the range are deleted. Right-click or **Esc** cancels.

### Mark as Invalid

Defines an interactive two-click range on the signal; events within the range are marked as bad.
Right-click or **Esc** cancels.

### Remove Invalid Mark

Defines an interactive two-click range on the signal; clears the bad flag for events within the range.


## Periods

### Manage

Opens the periods vocabulary dialog, which displays visibility, period IDs, names, and colors. You can show or hide individual 
period types and use the same editing patterns as for events: add or remove entries, rename entries in place, and select colors.
The **Add** button is enabled when a type is selected: click twice on the signal to set the start and end of the period (which may span sweeps). 
Right-click or **Esc** cancels.

## Add-ons

### Manage

Opens the Add-on Manage dialog to browse the catalog, install, update, uninstall, and inspect package metadata.
See [Add-ons Usage](../add_ons/usage.md).

### Create

Opens the template generator that scaffolds a development add-on in the local add-ons folder (`./add_on_development` by default; choose another folder in **Add-ons → Manage**).
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
