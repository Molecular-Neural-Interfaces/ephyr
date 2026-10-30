# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from copy import deepcopy
from typing import Dict, List, Optional, Tuple

from ephyr.core.ephyr_session import Event, UserSession, EventVocabularyEntry
from ephyr.gui.vocabulary_names import companion_vocabulary_color
from .base import BaseCommand


class ModifyEventsCommand(BaseCommand):
    """Command that modifies the events list by saving/restoring the entire list."""
    should_emit_events_changed: bool = False
    should_emit_vocabulary_changed: bool = False

    def __init__(self):
        self._old_events: Optional[List[Event]] = None
        self._new_events: Optional[List[Event]] = None
        self._old_vocabulary: Optional[Dict[int, EventVocabularyEntry]] = None
        self._new_vocabulary: Optional[Dict[int, EventVocabularyEntry]] = None

    def do(self, wrapper) -> None:
        session = wrapper._session_manager.current_user_session
        if wrapper._session_manager.current_user_session is None:
            return

        if self._old_events is None:
            # First execution: save current state
            self._old_events = deepcopy(session.events)
            self._old_vocabulary = deepcopy(session.events_vocabulary)

            self._apply_change(session)

            self._new_events = deepcopy(session.events)
            self._new_vocabulary = deepcopy(session.events_vocabulary)
        else:
            # Redo: restore new state
            session.events = deepcopy(self._new_events)
            session.events_vocabulary = deepcopy(self._new_vocabulary)

        if self.should_emit_vocabulary_changed:
            wrapper.events_vocabulary_changed.emit(wrapper.events_vocabulary)
        if self.should_emit_events_changed:
            wrapper.events_changed.emit(wrapper.events)

    def undo(self, wrapper) -> None:
        session = wrapper._session_manager.current_user_session
        if session is None or self._old_events is None:
            return

        # Restore old state
        session.events = deepcopy(self._old_events)
        session.events_vocabulary = deepcopy(self._old_vocabulary)
        if self.should_emit_vocabulary_changed:
            wrapper.events_vocabulary_changed.emit(wrapper.events_vocabulary)
        if self.should_emit_events_changed:
            wrapper.events_changed.emit(wrapper.events)

    def _apply_change(self, session: UserSession) -> None:
        """Override this to apply the actual change to session.events."""
        raise NotImplementedError


class AddEventCommand(ModifyEventsCommand):
    """Command for adding a single event."""
    description = "add event"
    should_emit_events_changed = True

    def __init__(self, event_name_id: int, t_ms: float):
        super().__init__()
        self.event_name_id = event_name_id
        self.t_ms = t_ms

    def _apply_change(self, session: UserSession) -> None:
        session.add_event(self.event_name_id, self.t_ms)


class AddEventsCommand(ModifyEventsCommand):
    """Command for adding multiple events at once."""
    description = "add events"
    should_emit_events_changed = True

    def __init__(self, events_specs: List[Tuple[int, float]]):
        """
        events_specs: list of (event_name_id, t_ms)
        """
        super().__init__()
        self._events_specs: List[Tuple[int, float]] = list(events_specs)

    def _apply_change(self, session: UserSession) -> None:
        for event_name_id, t_ms in self._events_specs:
            session.add_event(event_name_id, t_ms)


class RemoveEventsCommand(ModifyEventsCommand):
    """Command for removing a batch of events."""
    description = "remove events"
    should_emit_events_changed = True

    def __init__(self, events: List[Event]):
        super().__init__()
        self._event_ids = {ev.id for ev in events}

    def _apply_change(self, session: UserSession) -> None:
        session.events = [ev for ev in session.events if ev.id not in self._event_ids]


class SetEventsBadFlagCommand(ModifyEventsCommand):
    """Command for setting or unsetting is_bad flag on a batch of events."""
    should_emit_events_changed = True

    def __init__(self, events: List[Event], is_bad: bool):
        super().__init__()
        self._event_ids = {ev.id for ev in events}
        self._new_is_bad: bool = is_bad
        self.description = "mark as invalid" if is_bad else "remove invalid mark"

    def _apply_change(self, session: UserSession) -> None:
        for ev in session.events:
            if ev.id in self._event_ids:
                ev.is_bad = self._new_is_bad


class AddEventVocabularyCommand(ModifyEventsCommand):
    """Command for adding a new event vocabulary entry."""
    description = "add event vocabulary"
    should_emit_vocabulary_changed = True

    def __init__(self, name: Optional[str] = None):
        super().__init__()
        self._name = name
        self._added_id: Optional[int] = None

    def _apply_change(self, session: UserSession) -> None:
        self._added_id = session.add_event_vocabulary(self._name)

    def get_added_id(self) -> Optional[int]:
        """Get the ID of the added vocabulary entry."""
        return self._added_id


class SetEventVocabularyNameCommand(ModifyEventsCommand):
    description = "rename event vocabulary"
    should_emit_events_changed = True
    should_emit_vocabulary_changed = True

    def __init__(self, event_vocabulary_id: int, name: str):
        super().__init__()
        self._event_vocabulary_id = event_vocabulary_id
        self._name = name

    def _apply_change(self, session: UserSession) -> None:
        session.rename_event_vocabulary(self._event_vocabulary_id, self._name)


class SetEventVocabularyColorCommand(ModifyEventsCommand):
    description = "change event vocabulary color"
    should_emit_events_changed = True
    should_emit_vocabulary_changed = True

    def __init__(self, event_vocabulary_id: int, color: str):
        super().__init__()
        self._event_vocabulary_id = event_vocabulary_id
        self._color = color

    def _apply_change(self, session: UserSession) -> None:
        session.set_event_vocabulary_color(self._event_vocabulary_id, self._color)


class SetEventVocabularyVisibilityCommand(ModifyEventsCommand):
    description = "change event vocabulary visibility"
    should_emit_events_changed = True
    should_emit_vocabulary_changed = True

    def __init__(self, event_vocabulary_id: int, is_visible: bool):
        super().__init__()
        self._event_vocabulary_id = event_vocabulary_id
        self._is_visible = is_visible

    def _apply_change(self, session: UserSession) -> None:
        session.set_event_vocabulary_visibility(self._event_vocabulary_id, self._is_visible)


class RemoveEventVocabularyCommand(ModifyEventsCommand):
    description = "remove event vocabulary"
    should_emit_events_changed = True
    should_emit_vocabulary_changed = True

    def __init__(self, event_vocabulary_id: int):
        super().__init__()
        self._event_vocabulary_id = event_vocabulary_id

    def _apply_change(self, session: UserSession) -> None:
        session.remove_event_vocabulary(self._event_vocabulary_id)


class ImportVocabularyAndEventsCommand(ModifyEventsCommand):
    """Command that imports events vocabulary and events with ID remapping."""
    description = "import events"
    should_emit_events_changed = True
    should_emit_vocabulary_changed = True

    def __init__(self, imported_vocabulary: Dict[int, EventVocabularyEntry], imported_events: List[Event]):
        super().__init__()
        self._imported_vocabulary = deepcopy(imported_vocabulary)
        self._imported_events = deepcopy(imported_events)

    def _apply_change(self, session: UserSession) -> None:
        id_mapping: Dict[int, int] = {}
        next_vocabulary_id = max(session.events_vocabulary.keys(), default=-1) + 1

        for old_id, entry in sorted(self._imported_vocabulary.items(), key=lambda item: item[0]):
            new_id = next_vocabulary_id
            next_vocabulary_id += 1
            session.events_vocabulary[new_id] = deepcopy(entry)
            id_mapping[old_id] = new_id

        next_event_id = session.next_event_id()
        for event in self._imported_events:
            mapped_event_name_id = id_mapping.get(event.event_name_id)
            if mapped_event_name_id is None:
                continue
            session.events.append(
                event.model_copy(update={"id": next_event_id, "event_name_id": mapped_event_name_id}, deep=True)
            )
            next_event_id += 1

        session.sort_events()


class SplitEventVocabularyCommand(ModifyEventsCommand):
    """Replace one event group with two. Checked events keep the first new name."""
    description = "split event group"
    should_emit_events_changed = True
    should_emit_vocabulary_changed = True

    def __init__(
        self,
        event_vocabulary_id: int,
        selected_event_ids: List[int],
        selected_name: str,
        other_name: str,
    ):
        super().__init__()
        self._vocabulary_id = event_vocabulary_id
        self._selected_event_ids = list(selected_event_ids)
        self._selected_name = selected_name
        self._other_name = other_name
        self._created_ids: Optional[Tuple[int, int]] = None
        self.selected_count = 0
        self.other_count = 0

    def get_created_ids(self) -> Optional[Tuple[int, int]]:
        return self._created_ids

    def _apply_change(self, session: UserSession) -> None:
        source = session.events_vocabulary.get(self._vocabulary_id)
        if source is None:
            raise ValueError("Event group does not exist")

        group_ids = {event.id for event in session.events if event.event_name_id == self._vocabulary_id}
        selected_ids = set(self._selected_event_ids) & group_ids
        if not selected_ids or selected_ids == group_ids:
            raise ValueError("Select some events and leave at least one in the other group")

        selected_name = self._selected_name.strip()
        other_name = self._other_name.strip()
        if not selected_name or not other_name:
            raise ValueError("Both groups need a name")
        if selected_name == other_name:
            raise ValueError("The two groups need different names")

        taken = {
            entry.name
            for vocabulary_id, entry in session.events_vocabulary.items()
            if vocabulary_id != self._vocabulary_id
        }
        if selected_name in taken or other_name in taken:
            raise ValueError("A group with this name already exists")

        selected_vocabulary_id = max(session.events_vocabulary) + 1
        other_vocabulary_id = selected_vocabulary_id + 1
        session.events_vocabulary.pop(self._vocabulary_id)
        session.events_vocabulary[selected_vocabulary_id] = EventVocabularyEntry(
            name=selected_name,
            color=source.color,
            is_visible=source.is_visible,
        )
        session.events_vocabulary[other_vocabulary_id] = EventVocabularyEntry(
            name=other_name,
            color=companion_vocabulary_color(source.color),
            is_visible=source.is_visible,
        )
        for event in session.events:
            if event.id in selected_ids:
                event.event_name_id = selected_vocabulary_id
            elif event.event_name_id == self._vocabulary_id:
                event.event_name_id = other_vocabulary_id

        self._created_ids = (selected_vocabulary_id, other_vocabulary_id)
        self.selected_count = len(selected_ids)
        self.other_count = len(group_ids) - len(selected_ids)


class MergeEventVocabularyCommand(ModifyEventsCommand):
    """Replace two or more event groups with one group."""
    description = "merge event groups"
    should_emit_events_changed = True
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
        if any(vocabulary_id not in session.events_vocabulary for vocabulary_id in vocabulary_ids):
            raise ValueError("Event group does not exist")

        name = self._name.strip()
        if not name:
            raise ValueError("Enter a name for the merged group")

        removed = set(vocabulary_ids)
        taken = {
            entry.name
            for vocabulary_id, entry in session.events_vocabulary.items()
            if vocabulary_id not in removed
        }
        if name in taken:
            raise ValueError(f"Name '{name}' is already used")

        donor_id = min(vocabulary_ids)
        donor = session.events_vocabulary[donor_id]
        is_visible = any(session.events_vocabulary[vocabulary_id].is_visible for vocabulary_id in vocabulary_ids)
        next_id = max(session.events_vocabulary) + 1

        for vocabulary_id in vocabulary_ids:
            session.events_vocabulary.pop(vocabulary_id, None)
        session.events_vocabulary[next_id] = EventVocabularyEntry(
            name=name,
            color=donor.color,
            is_visible=is_visible,
        )
        for event in session.events:
            if event.event_name_id in removed:
                event.event_name_id = next_id
        self._created_id = next_id
