# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

class WrongSourceReaderError(Exception):
    def __init__(self, parser_class):
        super().__init__(f"Wrong source reader class: {parser_class}.")
