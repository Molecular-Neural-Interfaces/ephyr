# Copyright (C) 2026 Life Improvement by Future Technologies (LIFT)
# SPDX-License-Identifier: GPL-3.0-only

from copy import deepcopy
from typing import Dict, List, Optional, Tuple

from ephyr.core.ephyr_session import Event, UserSession, EventVocabularyEntry
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
