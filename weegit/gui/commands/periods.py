from copy import deepcopy
from typing import Dict, List, Optional

from weegit.core.weegit_session import Period, UserSession, PeriodVocabularyEntry
from .base import BaseCommand


class ModifyPeriodsCommand(BaseCommand):
    """Command that modifies the periods list by saving/restoring the entire list."""
    should_emit_periods_changed: bool = False
    should_emit_vocabulary_changed: bool = False

    def __init__(self):
        self._old_periods: Optional[List[Period]] = None
        self._new_periods: Optional[List[Period]] = None
        self._old_vocabulary: Optional[Dict[int, PeriodVocabularyEntry]] = None
        self._new_vocabulary: Optional[Dict[int, PeriodVocabularyEntry]] = None

    def do(self, wrapper) -> None:
        session = wrapper._session_manager.current_user_session
        if wrapper._session_manager.current_user_session is None:
            return

        if self._old_periods is None:
            # First execution: save current state
            self._old_periods = deepcopy(session.periods)
            self._old_vocabulary = deepcopy(session.periods_vocabulary)

            self._apply_change(session)

            self._new_periods = deepcopy(session.periods)
            self._new_vocabulary = deepcopy(session.periods_vocabulary)
        else:
            # Redo: restore new state
            session.periods = deepcopy(self._new_periods)
            session.periods_vocabulary = deepcopy(self._new_vocabulary)

        if self.should_emit_vocabulary_changed:
            wrapper.periods_vocabulary_changed.emit(wrapper.periods_vocabulary)
        if self.should_emit_periods_changed:
            wrapper.periods_changed.emit(wrapper.periods)

    def undo(self, wrapper) -> None:
        session = wrapper._session_manager.current_user_session
        if session is None or self._old_periods is None:
            return

        # Restore old state
        session.periods = deepcopy(self._old_periods)
        session.periods_vocabulary = deepcopy(self._old_vocabulary)
        if self.should_emit_vocabulary_changed:
            wrapper.periods_vocabulary_changed.emit(wrapper.periods_vocabulary)
        if self.should_emit_periods_changed:
            wrapper.periods_changed.emit(wrapper.periods)

    def _apply_change(self, session: UserSession) -> None:
        """Override this to apply the actual change to session.periods."""
        raise NotImplementedError


class AddPeriodCommand(ModifyPeriodsCommand):
    """Command for adding a single period."""
    description = "add period"
    should_emit_periods_changed = True

    def __init__(self,        
        period_name_id: int,
        start_sweep_idx: int,
        start_time_ms: float,
        end_sweep_idx: int,
        end_time_ms: float,):
        super().__init__()
        self.period_name_id=period_name_id
        self.start_sweep_idx=start_sweep_idx
        self.start_time_ms=start_time_ms
        self.end_sweep_idx=end_sweep_idx
        self.end_time_ms=end_time_ms

    def _apply_change(self, session: UserSession) -> None:
        session.add_period(self.period_name_id, self.start_sweep_idx, 
                           self.start_time_ms, self.end_sweep_idx, self.end_time_ms)


class RemovePeriodsCommand(ModifyPeriodsCommand):
    """Command for removing a batch of periods."""
    description = "remove periods"
    should_emit_periods_changed = True

    def __init__(self, periods: List[Period]):
        super().__init__()
        # Store period identifiers instead of references (for deepcopy compatibility)
        self._periods_to_remove_ids: List[tuple[int, int, float, int, float]] = [
            (ev.period_name_id, ev.start_sweep_idx, ev.start_time_ms, ev.end_sweep_idx, ev.end_time_ms)
            for ev in periods
        ]

    def _apply_change(self, session: UserSession) -> None:
        # Find and remove periods by their identifiers
        periods_to_remove = [
            ev for ev in session.periods
            if (
                ev.period_name_id,
                ev.start_sweep_idx,
                ev.start_time_ms,
                ev.end_sweep_idx,
                ev.end_time_ms,
            ) in self._periods_to_remove_ids
        ]
        for ev in periods_to_remove:
            session.remove_period(ev)


class AddPeriodVocabularyCommand(ModifyPeriodsCommand):
    """Command for adding a new period vocabulary entry."""
    description = "add period vocabulary"
    should_emit_vocabulary_changed = True

    def __init__(self, name: Optional[str] = None):
        super().__init__()
        self._name = name
        self._added_id: Optional[int] = None

    def _apply_change(self, session: UserSession) -> None:
        self._added_id = session.add_period_vocabulary(self._name)

    def get_added_id(self) -> Optional[int]:
        """Get the ID of the added vocabulary entry."""
        return self._added_id


class SetPeriodVocabularyNameCommand(ModifyPeriodsCommand):
    description = "rename period vocabulary"
    should_emit_periods_changed = True
    should_emit_vocabulary_changed = True

    def __init__(self, period_vocabulary_id: int, name: str):
        super().__init__()
        self._period_vocabulary_id = period_vocabulary_id
        self._name = name

    def _apply_change(self, session: UserSession) -> None:
        session.rename_period_vocabulary(self._period_vocabulary_id, self._name)


class SetPeriodVocabularyColorCommand(ModifyPeriodsCommand):
    description = "change period vocabulary color"
    should_emit_periods_changed = True
    should_emit_vocabulary_changed = True

    def __init__(self, period_vocabulary_id: int, color: str):
        super().__init__()
        self._period_vocabulary_id = period_vocabulary_id
        self._color = color

    def _apply_change(self, session: UserSession) -> None:
        session.set_period_vocabulary_color(self._period_vocabulary_id, self._color)


class RemovePeriodVocabularyCommand(ModifyPeriodsCommand):
    description = "remove period vocabulary"
    should_emit_periods_changed = True
    should_emit_vocabulary_changed = True

    def __init__(self, period_vocabulary_id: int):
        super().__init__()
        self._period_vocabulary_id = period_vocabulary_id

    def _apply_change(self, session: UserSession) -> None:
        session.remove_period_vocabulary(self._period_vocabulary_id)


class ImportVocabularyAndPeriodsCommand(ModifyPeriodsCommand):
    """Command that imports periods vocabulary and periods with ID remapping."""
    description = "import periods"
    should_emit_periods_changed = True
    should_emit_vocabulary_changed = True

    def __init__(self, imported_vocabulary: Dict[int, PeriodVocabularyEntry], imported_periods: List[Period]):
        super().__init__()
        self._imported_vocabulary = deepcopy(imported_vocabulary)
        self._imported_periods = deepcopy(imported_periods)

    def _apply_change(self, session: UserSession) -> None:
        id_mapping: Dict[int, int] = {}
        next_vocabulary_id = max(session.periods_vocabulary.keys(), default=-1) + 1

        for old_id, entry in sorted(self._imported_vocabulary.items(), key=lambda item: item[0]):
            new_id = next_vocabulary_id
            next_vocabulary_id += 1
            session.periods_vocabulary[new_id] = deepcopy(entry)
            id_mapping[old_id] = new_id

        for period in self._imported_periods:
            mapped_period_name_id = id_mapping.get(period.period_name_id)
            if mapped_period_name_id is None:
                continue
            session.periods.append(
                Period(
                    period_name_id=mapped_period_name_id,
                    start_sweep_idx=period.start_sweep_idx,
                    start_time_ms=period.start_time_ms,
                    end_sweep_idx=period.end_sweep_idx,
                    end_time_ms=period.end_time_ms,
                )
            )
