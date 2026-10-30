# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from copy import deepcopy
from typing import Dict, List, Optional, Tuple

from ephyr.core.ephyr_session import Period, UserSession, PeriodVocabularyEntry
from ephyr.gui.vocabulary_names import companion_vocabulary_color
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

    def __init__(self, period_name_id: int, start_t_ms: float, end_t_ms: float):
        super().__init__()
        self.period_name_id = period_name_id
        self.start_t_ms = start_t_ms
        self.end_t_ms = end_t_ms

    def _apply_change(self, session: UserSession) -> None:
        session.add_period(self.period_name_id, self.start_t_ms, self.end_t_ms)


class RemovePeriodsCommand(ModifyPeriodsCommand):
    """Command for removing a batch of periods."""
    description = "remove periods"
    should_emit_periods_changed = True

    def __init__(self, periods: List[Period]):
        super().__init__()
        self._period_ids = {period.id for period in periods}

    def _apply_change(self, session: UserSession) -> None:
        session.periods = [period for period in session.periods if period.id not in self._period_ids]


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


class SetPeriodVocabularyVisibilityCommand(ModifyPeriodsCommand):
    description = "change period vocabulary visibility"
    should_emit_periods_changed = True
    should_emit_vocabulary_changed = True

    def __init__(self, period_vocabulary_id: int, is_visible: bool):
        super().__init__()
        self._period_vocabulary_id = period_vocabulary_id
        self._is_visible = is_visible

    def _apply_change(self, session: UserSession) -> None:
        session.set_period_vocabulary_visibility(self._period_vocabulary_id, self._is_visible)


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

        next_period_id = session.next_period_id()
        for period in self._imported_periods:
            mapped_period_name_id = id_mapping.get(period.period_name_id)
            if mapped_period_name_id is None:
                continue
            session.periods.append(
                period.model_copy(update={"id": next_period_id, "period_name_id": mapped_period_name_id}, deep=True)
            )
            next_period_id += 1
        session.sort_periods()


def _retarget_period_label(session: UserSession, removed_ids: set[int], replacement_id: int) -> None:
    """Keep period navigation pointing at a group that still exists."""
    if session.gui_setup.period_label_id in removed_ids:
        session.gui_setup.period_label_id = replacement_id


class _RetargetPeriodLabelCommand(ModifyPeriodsCommand):
    """Saves the period-navigation label so undo puts it back with the groups."""

    def __init__(self):
        super().__init__()
        self._label_saved = False
        self._old_label_id: Optional[int] = None
        self._new_label_id: Optional[int] = None

    def do(self, wrapper) -> None:
        first = self._old_periods is None
        session = wrapper._session_manager.current_user_session
        if first and session is not None:
            self._old_label_id = session.gui_setup.period_label_id
            self._label_saved = True
        elif session is not None and self._label_saved:
            session.gui_setup.period_label_id = self._new_label_id
        super().do(wrapper)
        if first and self._label_saved:
            session = wrapper._session_manager.current_user_session
            if session is not None:
                self._new_label_id = session.gui_setup.period_label_id

    def undo(self, wrapper) -> None:
        session = wrapper._session_manager.current_user_session
        if session is not None and self._label_saved:
            session.gui_setup.period_label_id = self._old_label_id
        super().undo(wrapper)


class SplitPeriodVocabularyCommand(_RetargetPeriodLabelCommand):
    """Replace one period group with two. Checked periods keep the first new name."""
    description = "split period group"
    should_emit_periods_changed = True
    should_emit_vocabulary_changed = True

    def __init__(
        self,
        period_vocabulary_id: int,
        selected_period_ids: List[int],
        selected_name: str,
        other_name: str,
    ):
        super().__init__()
        self._vocabulary_id = period_vocabulary_id
        self._selected_period_ids = list(selected_period_ids)
        self._selected_name = selected_name
        self._other_name = other_name
        self._created_ids: Optional[Tuple[int, int]] = None
        self.selected_count = 0
        self.other_count = 0

    def get_created_ids(self) -> Optional[Tuple[int, int]]:
        return self._created_ids

    def _apply_change(self, session: UserSession) -> None:
        source = session.periods_vocabulary.get(self._vocabulary_id)
        if source is None:
            raise ValueError("Period group does not exist")

        group_ids = {period.id for period in session.periods if period.period_name_id == self._vocabulary_id}
        selected_ids = set(self._selected_period_ids) & group_ids
        if not selected_ids or selected_ids == group_ids:
            raise ValueError("Select some periods and leave at least one in the other group")

        selected_name = self._selected_name.strip()
        other_name = self._other_name.strip()
        if not selected_name or not other_name:
            raise ValueError("Both groups need a name")
        if selected_name == other_name:
            raise ValueError("The two groups need different names")

        taken = {
            entry.name
            for vocabulary_id, entry in session.periods_vocabulary.items()
            if vocabulary_id != self._vocabulary_id
        }
        if selected_name in taken or other_name in taken:
            raise ValueError("A group with this name already exists")

        selected_vocabulary_id = max(session.periods_vocabulary) + 1
        other_vocabulary_id = selected_vocabulary_id + 1
        session.periods_vocabulary.pop(self._vocabulary_id)
        session.periods_vocabulary[selected_vocabulary_id] = PeriodVocabularyEntry(
            name=selected_name,
            color=source.color,
            is_visible=source.is_visible,
        )
        session.periods_vocabulary[other_vocabulary_id] = PeriodVocabularyEntry(
            name=other_name,
            color=companion_vocabulary_color(source.color),
            is_visible=source.is_visible,
        )
        for period in session.periods:
            if period.id in selected_ids:
                period.period_name_id = selected_vocabulary_id
            elif period.period_name_id == self._vocabulary_id:
                period.period_name_id = other_vocabulary_id

        _retarget_period_label(session, {self._vocabulary_id}, selected_vocabulary_id)
        self._created_ids = (selected_vocabulary_id, other_vocabulary_id)
        self.selected_count = len(selected_ids)
        self.other_count = len(group_ids) - len(selected_ids)


class MergePeriodVocabularyCommand(_RetargetPeriodLabelCommand):
    """Replace two or more period groups with one group."""
    description = "merge period groups"
    should_emit_periods_changed = True
    should_emit_vocabulary_changed = True

    def __init__(self, vocabulary_ids: List[int], name: str):
        super().__init__()
        self._vocabulary_ids = list(vocabulary_ids)
        self._name = name
        self._created_id: Optional[int] = None

    def get_created_id(self) -> Optional[int]:
        return self._created_id

    def _apply_change(self, session: UserSession) -> None:
        vocabulary_ids = list(dict.fromkeys(self._vocabulary_ids))
        if len(vocabulary_ids) < 2:
            raise ValueError("Select at least two groups to merge")
        if any(vocabulary_id not in session.periods_vocabulary for vocabulary_id in vocabulary_ids):
            raise ValueError("Period group does not exist")

        name = self._name.strip()
        if not name:
            raise ValueError("Enter a name for the merged group")

        removed = set(vocabulary_ids)
        taken = {
            entry.name
            for vocabulary_id, entry in session.periods_vocabulary.items()
            if vocabulary_id not in removed
        }
        if name in taken:
            raise ValueError(f"Name '{name}' is already used")

        donor_id = min(vocabulary_ids)
        donor = session.periods_vocabulary[donor_id]
        is_visible = any(session.periods_vocabulary[vocabulary_id].is_visible for vocabulary_id in vocabulary_ids)
        next_id = max(session.periods_vocabulary) + 1

        for vocabulary_id in vocabulary_ids:
            session.periods_vocabulary.pop(vocabulary_id, None)
        session.periods_vocabulary[next_id] = PeriodVocabularyEntry(
            name=name,
            color=donor.color,
            is_visible=is_visible,
        )
        for period in session.periods:
            if period.period_name_id in removed:
                period.period_name_id = next_id

        _retarget_period_label(session, removed, next_id)
        self._created_id = next_id
