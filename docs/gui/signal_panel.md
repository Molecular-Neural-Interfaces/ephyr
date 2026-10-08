# Data Panel

The data panel serves as the main workspace for viewing and labeling recordings once an experiment session is loaded.

## How data is shown

Signal samples are loaded from the Ephyr experiment folder (`data/sweep_*/*.samples`) together with
`header.json`. Traces are arranged into **channel groups** defined in the current session’s GUI setup.

Each group can show a classic single-column stack of channels or a custom electrode grid (see
[Channel Management](settings_panel.md#channel-management)). Per-channel scale, color, Y offset, and
optional clipping apply when drawing. Channel name labels on each cell can be hidden with
**View → Channel names**.

## Data panel navigation

Below the traces:

- Scrollbar sets the window start sample. You can also move it with the mouse scroll by hovering over it.
- `<` and  `>` step by the configured timebar step
- `<<` and `>>` toggle auto-scroll: the view jumps by the timebar step on each frame, and the frame delay 
determines how often this occurs (1000 ms by default). In Beginner mode, the timebar step is half of the visible duration window.
- **Event / period navigator** — a strip of labels for events and period starts/ends in the current view. 
Arrow controls jump to the previous or next occurrence of the same event name within the sweep and 
recenter the time window. A period start has a right arrow that jumps to its end; a period end has a 
left arrow that jumps to its start, including periods whose boundaries are in different sweeps.

**Drag horizontally on the data panel** to move the view (when not in an exclusive overlay mode). 
Use **Ctrl/Cmd + scroll** to zoom the duration around the cursor.

When a channel group uses a large custom grid, a small **group navigator** (arrows + minimap) appears, 
which you can use to move the visible window of electrodes within that group.

## Events and periods

The following items can be placed on top of the traces:

- **Events** — vertical markers at a specific time in a sweep, colored by vocabulary entry. Events can be flagged as bad. 
Use the Events menu for vocabulary management and for interactive add, remove, and bad-flag modes. 
- **Periods** — labeled intervals that may span sweeps. Use the Periods menu to manage vocabulary and to add intervals with two clicks. 

Global visibility of channel traces, channel names, events, and periods is controlled from **View**. 
Individual event and period types can also be hidden in their vocabulary dialogs. Markers remain visible over disabled channels. 
These settings are stored in the session.

## Interactive tools

| Mode | How to start                                | What it does |
|------|---------------------------------------------|--------------|
| Measurement bar | Press **M** (cycles: follow → freeze → off) | Time and voltage scale bars at the cursor |
| Full-view select | Press **V**                                 | Two clicks define a rectangle; the cursor label is **Select area**. Opens a dialog with the selected area |
| Event / period modes | Events and Periods menus                    | Crosshair overlay for placing or editing labels; **Esc** or right-click cancels |

## Add-on overlays

Viewable add-ons render additional graphics on the same panel after the base traces, according to their 
z-order relative to periods and events. A common example is the **CSD** (current source density) add-on. 
Another example is highlighted **spikes** from the Spike viewer add-on: detection results stored under 
`add_ons/data/` are rendered as markers on the relevant channels.

![Signal panel with add-on overlays](../source/_static/gui/signal_panel_addons.png)

Transformation add-ons do not draw; they modify the numeric samples that feed the display pipeline prior 
to filtering and plotting. Runnable add-ons are started from the Add-ons settings section and may update
session labels or files that Viewable tools subsequently display.