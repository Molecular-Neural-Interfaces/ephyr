# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

"""Configurable preprocessing pipelines shared by all add-ons.

A pipeline is an ordered list of steps applied to a ``(n_channels, n_samples)``
matrix. Steps cover trimming, baseline correction, band filtering, notch, and
artefact removal. Pipelines are stored as JSON in the shared
``$SESSION/add_ons/data/ephyr`` folder so every add-on sees the same set of
named pipelines within a session.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, Field

from ephyr.core.conversions.filters import (
    ButterworthBandPassFilter,
    ButterworthHighPassFilter,
    ButterworthLowPassFilter,
    NotchFilter,
)
from ephyr.logger import ephyr_logger

PIPELINES_FILENAME = "preprocessing_pipelines.json"
DEFAULT_PIPELINE_NAME = "raw"

# Ordered step kinds with human labels used by the pipeline builder UI.
STEP_KINDS: Dict[str, str] = {
    "trim": "Trim initial segment",
    "baseline": "Polynomial baseline correction",
    "highpass": "Butterworth high-pass",
    "lowpass": "Butterworth low-pass",
    "bandpass": "Butterworth band-pass",
    "notch": "Notch (line noise)",
    "artifact_removal": "Artifact removal (robust-z blanking)",
}


class PreprocessingStep(BaseModel):
    kind: str
    enabled: bool = True
    params: Dict[str, Any] = Field(default_factory=dict)


class PipelineSpec(BaseModel):
    name: str
    steps: List[PreprocessingStep] = Field(default_factory=list)
    description: str = ""


def default_pipeline_store() -> Dict[str, PipelineSpec]:
    return {
        DEFAULT_PIPELINE_NAME: PipelineSpec(
            name=DEFAULT_PIPELINE_NAME, steps=[], description="No preprocessing"
        )
    }


def _pipelines_path(path_or_dir: Path) -> Path:
    path = Path(path_or_dir)
    if path.is_dir() or path.name != PIPELINES_FILENAME:
        return path / PIPELINES_FILENAME if path.suffix == "" else path
    return path


def read_pipeline_store(path_or_dir: Path) -> Dict[str, PipelineSpec]:
    path = _pipelines_path(path_or_dir)
    if not path.exists():
        return default_pipeline_store()
    store: Dict[str, PipelineSpec] = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        for name, payload in (raw or {}).items():
            try:
                spec = PipelineSpec.model_validate(payload)
            except Exception as e:
                ephyr_logger().debug(str(e))
                continue
            clean_name = spec.name.strip() or str(name)
            spec.name = clean_name
            store[clean_name] = spec
    except Exception as e:
        ephyr_logger().debug(str(e))
    if DEFAULT_PIPELINE_NAME not in store:
        store.update(default_pipeline_store())
    return store


def write_pipeline_store(path_or_dir: Path, pipelines: Mapping[str, PipelineSpec]) -> Path:
    path = _pipelines_path(path_or_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {name: spec.model_dump() for name, spec in pipelines.items()}
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return path


# ---- Individual step implementations ----

def _filter_from_step(step: PreprocessingStep):
    params = dict(step.params or {})
    kind = step.kind.strip().lower()
    if kind == "notch":
        flt = NotchFilter()
        flt.notch_freq_hz = float(params.get("notch_freq_hz", 50.0))
        flt.q_factor = float(params.get("q_factor", 30.0))
    elif kind == "highpass":
        flt = ButterworthHighPassFilter()
        flt.cutoff_hz = float(params.get("cutoff_hz", 300.0))
        flt.order = int(params.get("order", 3))
    elif kind == "lowpass":
        flt = ButterworthLowPassFilter()
        flt.cutoff_hz = float(params.get("cutoff_hz", 3000.0))
        flt.order = int(params.get("order", 3))
    elif kind == "bandpass":
        flt = ButterworthBandPassFilter()
        flt.lowcut_hz = float(params.get("lowcut_hz", 300.0))
        flt.highcut_hz = float(params.get("highcut_hz", 3000.0))
        flt.order = int(params.get("order", 3))
    else:
        return None
    flt.enabled = True
    if hasattr(flt, "sos_cache"):
        flt.sos_cache = {}
    return flt


def apply_filter_step(matrix: np.ndarray, sample_rate: float, step: PreprocessingStep) -> np.ndarray:
    flt = _filter_from_step(step)
    x = np.asarray(matrix, dtype=np.float64)
    if flt is None:
        return x.copy()
    return np.vstack([flt.apply(row, float(sample_rate)) for row in x])


def apply_trim(matrix: np.ndarray, sample_rate: float, step: PreprocessingStep) -> np.ndarray:
    x = np.asarray(matrix, dtype=np.float64)
    trim_s = float((step.params or {}).get("trim_seconds", 0.0))
    trim_n = max(0, int(round(trim_s * float(sample_rate))))
    if trim_n <= 0 or trim_n >= x.shape[1]:
        return x.copy()
    return x[:, trim_n:].copy()


def apply_baseline(matrix: np.ndarray, step: PreprocessingStep) -> np.ndarray:
    x = np.asarray(matrix, dtype=np.float64)
    order = int((step.params or {}).get("order", 1))
    if x.shape[1] < order + 1:
        return x.copy()
    t = np.arange(x.shape[1], dtype=np.float64)
    out = np.empty_like(x)
    for i in range(x.shape[0]):
        coef = np.polyfit(t, x[i], deg=order)
        out[i] = x[i] - np.polyval(coef, t)
    return out


def _merge_windows(windows: Sequence[Tuple[int, int]], gap: int = 0) -> List[Tuple[int, int]]:
    clean = sorted((max(0, int(a)), max(0, int(b))) for a, b in windows if int(b) > int(a))
    if not clean:
        return []
    out = [list(clean[0])]
    for a, b in clean[1:]:
        if a <= out[-1][1] + int(gap):
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(int(a), int(b)) for a, b in out]


def detect_artifact_windows(
    matrix: np.ndarray,
    sample_rate: float,
    threshold_z: float = 5.0,
    min_distance_ms: float = 20.0,
    pre_ms: float = 5.0,
    post_ms: float = 25.0,
    merge_gap_ms: float = 5.0,
) -> List[Tuple[int, int]]:
    from scipy.signal import find_peaks

    x = np.asarray(matrix, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] == 0:
        return []
    med = np.median(x, axis=1, keepdims=True)
    mad = np.median(np.abs(x - med), axis=1, keepdims=True)
    z = np.abs((x - med) / (mad / 0.6745 + 1e-8))
    aggregate = np.median(z, axis=0)
    distance = max(1, int(round(float(min_distance_ms) * float(sample_rate) / 1000.0)))
    peaks, _props = find_peaks(aggregate, height=float(threshold_z), distance=distance)
    pre = max(0, int(round(float(pre_ms) * float(sample_rate) / 1000.0)))
    post = max(0, int(round(float(post_ms) * float(sample_rate) / 1000.0)))
    n = x.shape[1]
    gap = max(0, int(round(float(merge_gap_ms) * float(sample_rate) / 1000.0)))
    return _merge_windows([(max(0, int(pk) - pre), min(n, int(pk) + post + 1)) for pk in peaks], gap=gap)


def blank_artifact_windows(matrix: np.ndarray, windows: Sequence[Tuple[int, int]]) -> np.ndarray:
    x = np.asarray(matrix, dtype=np.float64)
    out = x.copy()
    for row_idx in range(out.shape[0]):
        row = out[row_idx]
        for a, b in windows:
            a = max(0, int(a))
            b = min(row.size, int(b))
            if b <= a:
                continue
            left = a - 1
            right = b
            if left < 0 and right >= row.size:
                row[a:b] = 0.0
            elif left < 0:
                row[a:b] = row[right]
            elif right >= row.size:
                row[a:b] = row[left]
            else:
                t = (np.arange(a, b) - left) / float(max(1, right - left))
                row[a:b] = (1.0 - t) * row[left] + t * row[right]
    return out


def apply_artifact_removal(matrix: np.ndarray, sample_rate: float, step: PreprocessingStep) -> np.ndarray:
    params = dict(step.params or {})
    windows = detect_artifact_windows(
        matrix=matrix,
        sample_rate=sample_rate,
        threshold_z=float(params.get("threshold_z", 5.0)),
        min_distance_ms=float(params.get("min_distance_ms", 20.0)),
        pre_ms=float(params.get("pre_ms", 5.0)),
        post_ms=float(params.get("post_ms", 25.0)),
        merge_gap_ms=float(params.get("merge_gap_ms", 5.0)),
    )
    return blank_artifact_windows(matrix, windows)


ProgressCallback = Callable[[int, int, str], None]


def step_label(step: PreprocessingStep) -> str:
    return STEP_KINDS.get(step.kind.strip().lower(), step.kind)


def enabled_steps(pipeline: Optional[PipelineSpec]) -> List[PreprocessingStep]:
    if pipeline is None:
        return []
    return [s for s in pipeline.steps if s.enabled]


def apply_single_step(matrix: np.ndarray, sample_rate: float, step: PreprocessingStep) -> np.ndarray:
    """Apply one preprocessing step and return the resulting matrix."""
    out = np.asarray(matrix, dtype=np.float64)
    kind = step.kind.strip().lower()
    try:
        if kind in {"notch", "highpass", "lowpass", "bandpass"}:
            return apply_filter_step(out, sample_rate, step)
        if kind == "trim":
            return apply_trim(out, sample_rate, step)
        if kind == "baseline":
            return apply_baseline(out, step)
        if kind == "artifact_removal":
            return apply_artifact_removal(out, sample_rate, step)
        if kind in {"cmr", "wavelet_denoise", "ica"}:
            # Removed from the supported set; skip if an old saved pipeline
            # still references them.
            ephyr_logger().debug(f"Skipping unsupported preprocessing step: {kind}")
            return out.copy()
    except Exception as e:
        ephyr_logger().debug(str(e))
    return out.copy()


def apply_preprocessing_pipeline(
    matrix: np.ndarray,
    sample_rate: float,
    pipeline: Optional[PipelineSpec],
    progress_cb: Optional[ProgressCallback] = None,
) -> np.ndarray:
    """Apply an ordered pipeline to a ``(n_channels, n_samples)`` matrix.

    ``progress_cb(step_index, total_steps, step_label)`` is invoked before each
    enabled step so callers can surface a "Preprocessing pipeline: <step>"
    screen while the work runs.
    """
    out = np.asarray(matrix, dtype=np.float64).copy()
    steps = enabled_steps(pipeline)
    total = len(steps)
    for idx, step in enumerate(steps, start=1):
        if progress_cb is not None:
            try:
                progress_cb(idx, total, step_label(step))
            except Exception as e:
                ephyr_logger().debug(str(e))
        out = apply_single_step(out, sample_rate, step)
    return out


__all__ = [
    "DEFAULT_PIPELINE_NAME",
    "PIPELINES_FILENAME",
    "STEP_KINDS",
    "PreprocessingStep",
    "PipelineSpec",
    "apply_preprocessing_pipeline",
    "apply_single_step",
    "enabled_steps",
    "step_label",
    "default_pipeline_store",
    "read_pipeline_store",
    "write_pipeline_store",
]
