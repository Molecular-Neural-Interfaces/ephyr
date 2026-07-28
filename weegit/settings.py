import os

from platformdirs import user_log_dir, user_data_dir


WEEGIT_FOLDER_SUFFIX = "_weegit"
SIGNAL_DATA_SUBFOLDER = "data"
SIGNAL_DATA_SWEEP_SUBFOLDER_PREFIX = "sweep_"
SIGNAL_DATA_EXTENSION = ".samples"  # weegit signal data
HEADER_FILENAME = "header.json"
SESSION_EXTENSION = ".json"
OTHER_SESSIONS_FOLDER = "sessions"
ADD_ONS_SUBFOLDER = "add_ons"
ADD_ONS_DATA_SUBFOLDER = "data"
MAX_UNDO_HISTORY_SIZE = 30

# Signal
DEFAULT_VISIBLE_CHANNELS_NUM = 32
MIN_DURATION = 1
MAX_DURATION = 1000 * 1000 * 60 * 30
MIN_TIME_STEP = 1
MAX_TIME_STEP = 1000 * 1000 * 60  # 1 min
MIN_SCALE = 0.000_000_001
MAX_SCALE = 100_000_000.0
MAX_START_POINT = 2_147_483_647  # max 32-bit integer
DEFAULT_SCALE = 1000
DEFAULT_DURATION = 10_000
DEFAULT_TIME_STEP = 1000
SCALE_STEP = 10
MEASURE_BAR_DIVIDER = 2
MIN_NUMBER_OF_DOTS_TO_DISPLAY = 1_000
MAX_NUMBER_OF_DOTS_TO_DISPLAY = 1_000_000
DEFAULT_NUMBER_OF_DOTS_TO_DISPLAY = 10_000
ANALOGUE_PANEL_HEIGHT = 120
DEFAULT_SPIKES_THRESHOLD = 5.0
CHANNELS_MAPPING_IMG_DEFAULT_WIDTH = 100
AUTO_SCROLL_STEP_INTERVAL_MS = 500

# global storage
APP_NAME = "weegit"
GLOBAL_STORAGE_FILENAME = "weegit.json"
RECENT_EXPERIMENTS_LIST_MAX_LENGTH = 8
LOG_DIRECTORY = user_log_dir(APP_NAME, appauthor=False)
ADD_ONS_DIRECTORY = user_data_dir(APP_NAME, appauthor=False)

# Add-ons
ADD_ONS_REPOSITORY = "https://github.com/misisisim/weegit-add-ons.git"
INDEX_RAW_URL = "https://raw.githubusercontent.com/misisisim/weegit-add-ons/main/index.json"
REPO_RAW_BASE = "https://raw.githubusercontent.com/misisisim/weegit-add-ons/main"

# Documentation
DOCUMENTATION_LINK = "https://weegit.github.io/weegit/"

# Logging
MAX_LOG_ITEMS = 60

# Development
DEBUG = bool(os.environ.get('WEEGIT_DEBUG', False))
