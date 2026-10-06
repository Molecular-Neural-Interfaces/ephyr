# Main Window

When an experiment session is open, the Ephyr window is organized as follows.

![Annotated main window](../source/_static/gui/main_window_annotated.png)

## Layout overview

| Region | Role |
|--------|------|
| **Menu** | Global actions: open experiments, manage sessions, toggle visibility, label events/periods, manage add-ons, and open Help. See [Menu](menu.md). |
| **Header bar** | **Scalebar** turns the time/voltage bar on or off. **Zoom to area** starts area selection (same as **V**). **Export Canvas** exports the current signal view (PNG/SVG). **Show session panel** / **Hide session panel** shows or hides the right-hand settings panel. |
| **Signal panel** (left) | Channel groups with traces, events, periods, optional add-on overlays, and time navigation. See [Signal Panel](signal_panel.md). |
| **Settings panel** (right) | Session panel (Beginner / Expert), timeline and channel settings, recording description, add-ons list, and application logs. See [Settings Panel](settings_panel.md). |
| **Status bar** | Timestamped status messages on the left. On the right: `Session: SESSION  |  Recording: parent_folder/EXP_NAME`. |

Before any experiment is loaded, the left area shows a start screen with a quick Open action and a short hotkey list.

## Signal panel highlights

Inside the signal panel you will typically work with:

- **Channel groups** — arranged traces for one or more electrode groups
- **Events** — point markers on the time axis
- **Periods** — labeled time intervals
- **Tools** — measurement bar, area selection, and interactive labeling modes
- **Add-on overlays** — drawings from Viewable add-ons (for example spike markers)
- **Time controls** — scrollbar, step buttons, and auto-scroll for navigating the recording

## Settings panel highlights

The right panel starts with **Session panel** (Beginner / Expert). Additional sections are toggled independently
from **View → Session Panel**: Recording Navigation, Timeline Settings, Channel management, Add-ons, Recording description, and
Application logs.
