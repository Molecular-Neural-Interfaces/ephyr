# Main Window

When an experiment session is open, the Ephyr window is organized as follows.

![Annotated main window](../source/_static/gui/main_window_annotated.png)

## Layout overview

| Region | Role |
|--------|------|
| **Menu** | Global actions include opening experiments, managing sessions, toggling visibility, labeling events and periods, managing add-ons, and opening Help. See [Menu](menu.md). |
| **Toolbar panel** | **Scalebar** turns the time/amplitude bar on or off. **Zoom to area** starts area selection (same as V). **Export Canvas** exports the current signal view (PNG/SVG). 
**Hide session panel** / **Show session panel** shows or hides the right-hand settings panel. |
| **Data panel** (left) | Contains channel groups with traces, events, periods, optional add-on overlays, and time navigation. See [Signal Panel](signal_panel.md). |
| **Settings panel** (right) | Includes mode selection (Beginner / Expert), timeline and channel settings, recording description, add-ons list, and application logs. See [Settings Panel](settings_panel.md). |
| **Status bar** | Timestamped status messages from the application. The current session name, recording name, and folder appear on the right.|

Before any experiment is loaded, the left area shows a start screen with a quick Open action and a short hotkey list.

## Data panel highlights

Inside the data panel you will typically work with:

- **Time controls** — scrollbar, step buttons, and auto-scroll for navigating the recording
- **Channel groups** — arranged traces for one or more electrode groups
- **Events** — point markers on the time axis
- **Periods** — labeled time intervals
- **Tools** — measurement bar, area selection, and interactive labeling modes
- **Add-on overlays** — drawings from Viewable add-ons (for example spike markers)

## Session panel highlights

The Session panel begins with a mode selection (Beginner / Expert).  Additional sections are toggled independently 
from **View → Session Panel**: Recording Navigation, Timeline settings, Channel management, Add-ons, 
Recording description and Application logs. Recording Navigation is disabled by default.
