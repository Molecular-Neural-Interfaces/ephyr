"""Shared, group-independent infrastructure for Weegit add-ons."""

from weegit.core.add_ons.common.ignore import (
    IgnoreEventsRule,
    IgnorePeriodsRule,
    build_valid_mask,
)
from weegit.core.add_ons.common.mixin import WeegitAddOnMixin
from weegit.core.add_ons.common.preprocessing import (
    DEFAULT_PIPELINE_NAME,
    PIPELINES_FILENAME,
    STEP_KINDS,
    PipelineSpec,
    PreprocessingStep,
    apply_preprocessing_pipeline,
    default_pipeline_store,
    read_pipeline_store,
    write_pipeline_store,
)
from weegit.core.add_ons.common.state import COMMON_SCOPE, SessionParamStore
from weegit.core.add_ons.common.widgets import (
    FilterEditor,
    PipelineBuilderDialog,
    PipelineSelector,
    filter_from_spec,
)

__all__ = [
    "COMMON_SCOPE",
    "DEFAULT_PIPELINE_NAME",
    "PIPELINES_FILENAME",
    "STEP_KINDS",
    "FilterEditor",
    "IgnoreEventsRule",
    "IgnorePeriodsRule",
    "PipelineBuilderDialog",
    "PipelineSelector",
    "PipelineSpec",
    "PreprocessingStep",
    "SessionParamStore",
    "WeegitAddOnMixin",
    "apply_preprocessing_pipeline",
    "build_valid_mask",
    "default_pipeline_store",
    "filter_from_spec",
    "read_pipeline_store",
    "write_pipeline_store",
]
