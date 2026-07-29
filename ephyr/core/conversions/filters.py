from abc import abstractmethod
from typing import Annotated, ClassVar, Dict, List, Optional, Type, Union, Literal

import numpy as np
from pydantic import BaseModel, Field
from scipy import signal


class BaseFilter(BaseModel):
    filter_type: str
    enabled: bool = False
    filter_name: ClassVar[str] = "Base filter"

    class Config:
        arbitrary_types_allowed = True

    @abstractmethod
    def apply(self, data: np.ndarray, sample_rate: float) -> np.ndarray:
        raise NotImplemented

    def required_sample_rate(self) -> float:
        return 0.0


class BaseIIRFilter(BaseFilter):
    order: int = 4
    sos_cache: Dict[float, np.ndarray] = Field(default_factory=dict, exclude=True)

    def _design_sos(self, sample_rate: float) -> Optional[np.ndarray]:
        raise NotImplemented

    def _get_sos(self, sample_rate: float) -> Optional[np.ndarray]:
        if sample_rate <= 0:
            return None
        if sample_rate in self.sos_cache:
            return self.sos_cache[sample_rate]
        sos = self._design_sos(sample_rate)
        if sos is not None:
            self.sos_cache[sample_rate] = sos
        return sos

    @staticmethod
    def _sos_padlen(sos: np.ndarray) -> int:
        # sosfiltfilt default padlen is 3 * (2 * n_sections - 1)
        return 3 * (2 * len(sos) - 1)

    def apply(self, data: np.ndarray, sample_rate: float) -> np.ndarray:
        if not self.enabled:
            return data
        sos = self._get_sos(sample_rate)
        if sos is None:
            return data
        try:
            return signal.sosfiltfilt(sos, data)
        except ValueError:
            return data


class ButterworthLowPassFilter(BaseIIRFilter):
    filter_type: Literal["butter_lowpass"] = "butter_lowpass"
    filter_name: ClassVar[str] = "Butterworth Low-pass"
    cutoff_hz: float = 300.0

    def _design_sos(self, sample_rate: float) -> Optional[np.ndarray]:
        nyq = sample_rate / 2.0
        if self.cutoff_hz <= 0 or self.cutoff_hz >= nyq:
            return None
        return signal.butter(self.order, self.cutoff_hz, btype="low", fs=sample_rate, output="sos")

    def required_sample_rate(self) -> float:
        return max(0.0, float(self.cutoff_hz) * 2.2)


class ButterworthHighPassFilter(BaseIIRFilter):
    filter_type: Literal["butter_highpass"] = "butter_highpass"
    filter_name: ClassVar[str] = "Butterworth High-pass"
    cutoff_hz: float = 1.0

    def _design_sos(self, sample_rate: float) -> Optional[np.ndarray]:
        nyq = sample_rate / 2.0
        if self.cutoff_hz <= 0 or self.cutoff_hz >= nyq:
            return None
        return signal.butter(self.order, self.cutoff_hz, btype="high", fs=sample_rate, output="sos")

    def required_sample_rate(self) -> float:
        return max(0.0, float(self.cutoff_hz) * 2.2)


class ButterworthBandPassFilter(BaseIIRFilter):
    filter_type: Literal["butter_bandpass"] = "butter_bandpass"
    filter_name: ClassVar[str] = "Butterworth Band-pass"
    lowcut_hz: float = 1.0
    highcut_hz: float = 300.0

    def _design_sos(self, sample_rate: float) -> Optional[np.ndarray]:
        nyq = sample_rate / 2.0
        if self.lowcut_hz <= 0 or self.highcut_hz <= 0:
            return None
        if self.lowcut_hz >= self.highcut_hz or self.highcut_hz >= nyq:
            return None
        return signal.butter(
            self.order,
            [self.lowcut_hz, self.highcut_hz],
            btype="bandpass",
            fs=sample_rate,
            output="sos",
        )

    def required_sample_rate(self) -> float:
        return max(0.0, float(self.highcut_hz) * 2.2)


class ChebyshevBandPassFilter(BaseIIRFilter):
    filter_type: Literal["cheby_bandpass"] = "cheby_bandpass"
    filter_name: ClassVar[str] = "Chebyshev Band-pass"
    lowcut_hz: float = 1.0
    highcut_hz: float = 300.0
    ripple_db: float = 1.0

    def _design_sos(self, sample_rate: float) -> Optional[np.ndarray]:
        nyq = sample_rate / 2.0
        if self.lowcut_hz <= 0 or self.highcut_hz <= 0:
            return None
        if self.lowcut_hz >= self.highcut_hz or self.highcut_hz >= nyq:
            return None
        ripple = max(0.1, float(self.ripple_db))
        return signal.cheby1(
            self.order,
            ripple,
            [self.lowcut_hz, self.highcut_hz],
            btype="bandpass",
            fs=sample_rate,
            output="sos",
        )

    def required_sample_rate(self) -> float:
        return max(0.0, float(self.highcut_hz) * 2.2)


class NotchFilter(BaseIIRFilter):
    filter_type: Literal["notch"] = "notch"
    filter_name: ClassVar[str] = "Notch (line noise)"
    notch_freq_hz: float = 50.0
    q_factor: float = 30.0

    def _design_sos(self, sample_rate: float) -> Optional[np.ndarray]:
        nyq = sample_rate / 2.0
        if self.notch_freq_hz <= 0 or self.notch_freq_hz >= nyq:
            return None
        q = max(0.1, float(self.q_factor))
        b, a = signal.iirnotch(self.notch_freq_hz, q, fs=sample_rate)
        return signal.tf2sos(b, a)

    def required_sample_rate(self) -> float:
        return max(0.0, float(self.notch_freq_hz) * 2.2)


FilterUnion = Union[
    ButterworthLowPassFilter,
    ButterworthHighPassFilter,
    ButterworthBandPassFilter,
    ChebyshevBandPassFilter,
    NotchFilter,
]
FilterConfig = Annotated[FilterUnion, Field(discriminator="filter_type")]


FILTER_REGISTRY: Dict[str, Type[BaseFilter]] = {
    ButterworthLowPassFilter.filter_name: ButterworthLowPassFilter,
    ButterworthHighPassFilter.filter_name: ButterworthHighPassFilter,
    ButterworthBandPassFilter.filter_name: ButterworthBandPassFilter,
    ChebyshevBandPassFilter.filter_name: ChebyshevBandPassFilter,
    NotchFilter.filter_name: NotchFilter,
}


def filter_class_by_name(name: str) -> Optional[Type[BaseFilter]]:
    return FILTER_REGISTRY.get(name)


def all_filter_names() -> List[str]:
    return list(FILTER_REGISTRY.keys())


def required_sample_rate_for_filters(filters: Optional[List[BaseFilter]]) -> float:
    if not filters:
        return 0.0
    required = 0.0
    for flt in filters:
        if getattr(flt, "enabled", False):
            required = max(required, float(flt.required_sample_rate()))
    return required


def default_filters() -> List[BaseFilter]:
    return [cls() for cls in FILTER_REGISTRY.values()]


def ensure_filters_list(filters: Optional[List[BaseFilter]]) -> List[BaseFilter]:
    existing = {flt.filter_type: flt for flt in (filters or [])}
    ordered = []
    for cls in FILTER_REGISTRY.values():
        flt = existing.get(cls().filter_type)
        ordered.append(flt if flt is not None else cls())
    return ordered
