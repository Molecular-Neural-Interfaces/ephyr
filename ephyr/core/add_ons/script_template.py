from __future__ import annotations

TEMPLATE = """from pathlib import Path

from ephyr.core.ephyr_session import EphyrSessionManager, UserSession

# Init manager and load experiment data.
session = EphyrSessionManager()
OUT_EPHYR_FOLDER = Path(r"{out_ephyr_folder}")
session.init_from_folder(OUT_EPHYR_FOLDER)

# Read raw sweep chunks and convert them to uV.
print("Header:", session.experiment_data.header)
sweep_idx, start_point, end_point = 0, 0, 10_000
for ch_idx in range(session.experiment_data.header.number_of_channels):
    raw_chunk = session.experiment_data.data_memmaps[sweep_idx][ch_idx][start_point:end_point]
    voltage_chunk_uv = session.experiment_data.from_int16_to_voltage_val(raw_chunk, ch_idx)
    ch_name = session.experiment_data.header.channel_info.name[ch_idx]
    print(f"Channel {{ch_idx}} [{{ch_name}}] peak |uV|: {{float(abs(voltage_chunk_uv).max()):.3f}}")

# Load GUI session (*.json in sessions/).
session_filename = UserSession.session_name_to_filename("{session_name}")
session.switch_sessions(session_filename)
print("GUI setup:", session.user_session.gui_setup)

{events_block}
{periods_block}
"""

EVENTS_BLOCK = """# Work with events table (merged with period context).
for event in session.user_session.events_table:
    # Skip events that belong to the period named PERIOD_NAME.
    if "PERIOD_NAME" in event.periods:
        continue
    print(
        f"event={event.name} sweep={event.sweep_idx} "
        f"time_ms={event.time_ms} bad={event.is_bad} periods={event.periods}"
    )
"""

PERIODS_BLOCK = """# Work with periods.
for period in session.user_session.periods:
    period_name = session.user_session.get_period_vocabulary_name(period.period_name_id)
    print(
        f"period={period_name} "
        f"start=({period.start_sweep_idx}, {period.start_time_ms} ms) "
        f"end=({period.end_sweep_idx}, {period.end_time_ms} ms)"
    )
"""

def render_script_template(
    *,
    out_ephyr_folder: str,
    session_name: str,
    include_events_block: bool = True,
    include_periods_block: bool = True,
) -> str:
    return TEMPLATE.format(
        out_ephyr_folder=out_ephyr_folder,
        session_name=session_name,
        events_block=EVENTS_BLOCK if include_events_block else "",
        periods_block=PERIODS_BLOCK if include_periods_block else "",
    )
