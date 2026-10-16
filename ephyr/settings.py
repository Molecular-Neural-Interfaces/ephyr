# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

import os

from platformdirs import user_log_dir, user_data_dir


EPHYR_FOLDER_SUFFIX = "_ephyr"
MANIFEST_EXTENSION = ".ephyr"
WORKSPACE_MANIFEST_FILENAME = "workspace.ephyr"
CONFIG_MANIFEST_FILENAME = "config.ephyr"
RECORD_MANIFEST_FILENAME = "record.ephyr"
CONFIGS_SUBFOLDER = "configs"
RECORDS_SUBFOLDER = "records"
SOURCES_SUBFOLDER = "sources"
SOURCE_ANNOTATIONS_SUBFOLDER = "source_annotations"
PARTIAL_RECORD_SUFFIX = ".partial"
SIGNAL_DATA_CHANNEL_FILE_PREFIX = "channel_"
SIGNAL_DATA_EXTENSION = ".samples"  # ephyr signal data
SESSIONS_SUBFOLDER = "sessions"
SESSION_SETTINGS_FILENAME = "settings.json"
EVENTS_FILENAME = "events.csv"
PERIODS_FILENAME = "periods.csv"
DEFAULT_SESSION_NAME = "default"
ADD_ONS_SUBFOLDER = "add_ons"
ADD_ONS_DATA_SUBFOLDER = "data"
MAX_UNDO_HISTORY_SIZE = 30

# Signal
DEFAULT_VISIBLE_CHANNELS_NUM = 32
MIN_DURATION = 1
MAX_DURATION = 2_147_483_647
MIN_TIME_STEP = 1
MAX_TIME_STEP = 2_147_483_647  # 1 hour
MIN_SCALE = 0.000_000_001
MAX_SCALE = 100_000_000.0
MAX_START_POINT = 2_147_483_647  # max 32-bit integer
DEFAULT_SCALE = 1000
SCALE_DECIMALS = 9
DEFAULT_DURATION = 10_000
DEFAULT_TIME_STEP = 1000
MEASURE_BAR_DIVIDER = 2
MIN_NUMBER_OF_DOTS_TO_DISPLAY = 1_000
MAX_NUMBER_OF_DOTS_TO_DISPLAY = 1_000_000
DEFAULT_NUMBER_OF_DOTS_TO_DISPLAY = 10_000
ANALOGUE_PANEL_HEIGHT = 120
DEFAULT_SPIKES_THRESHOLD = 5.0
VISUAL_ATTACHMENT_DEFAULT_WIDTH = 100
AUTO_SCROLL_STEP_INTERVAL_MS = 1000
OVERLAY_TRACE_COLOR = "#9B9B9B"
OVERLAY_TRACE_WIDTH = 1.0

MEASURE_BAR_TIME_VALUES = [1, 2, 5, 10, 20, 50, 100, 200, 500]

# global storage
APP_NAME = "ephyr"
GLOBAL_STORAGE_FILENAME = "ephyr.json"
RECENT_WORKSPACES_LIST_MAX_LENGTH = 8
LOG_DIRECTORY = user_log_dir(APP_NAME, appauthor=False)
ADD_ONS_DIRECTORY = user_data_dir(APP_NAME, appauthor=False)

# Add-ons
ADD_ONS_REPOSITORY = "https://github.com/Molecular-Neural-Interfaces/ephyr-add-ons.git"
INDEX_RAW_URL = "https://raw.github.com/Molecular-Neural-Interfaces/ephyr-add-ons/main/index.json"
REPO_RAW_BASE = "https://raw.github.com/Molecular-Neural-Interfaces/ephyr-add-ons/main"

# Documentation
DOCUMENTATION_LINK = "https://ephyr.readthedocs.io/en/latest/"

# Logging
MAX_LOG_ITEMS = 60

# Development
DEBUG = bool(int(os.environ.get('EPHYR_DEBUG', False)))
