"""Internal turn-execution and cross-process control boundary."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from .errors import AxiError
from .events import EventJournal
from .state import StateStore


class TurnExecutor:
    """Own control relay, collection, timeout, and journal finalization for one turn."""

    def __init__(self, store: StateStore, collect: Callable[..., Any]) -> None:
        self.store = store
        self.collect = collect

    def run(
        self,
        thread_id: str,
        turn: Any,
        *,
        timeout: float = 0,
        journal: EventJournal | None = None,
    ) -> Any:
        stop = threading.Event()

        def relay() -> None:
            while not stop.wait(0.05):
                for control in self.store.take_controls(thread_id):
                    try:
                        if control["action"] == "steer":
                            turn.steer(control["message"])
                        elif control["action"] == "interrupt":
                            turn.interrupt()
                        else:
                            raise ValueError("unknown control action")
                        self.store.finish_control(
                            control["id"], status="applied", thread_id=thread_id
                        )
                    except Exception as error:
                        self.store.finish_control(
                            control["id"],
                            status="rejected",
                            error=type(error).__name__,
                            thread_id=thread_id,
                        )

        relay_thread = threading.Thread(
            target=relay, name=f"codex-axi-control-{turn.id}", daemon=True
        )
        relay_thread.start()
        completed = threading.Event()
        outcome: dict[str, Any] = {}

        def collect() -> None:
            try:
                if journal is None:
                    outcome["result"] = self.collect(thread_id, turn)
                else:
                    outcome["result"] = self.collect(thread_id, turn, journal=journal)
            except BaseException as error:
                outcome["error"] = error
            finally:
                if journal is not None:
                    journal.finish()
                completed.set()

        collector = threading.Thread(target=collect, name=f"codex-axi-turn-{turn.id}", daemon=True)
        collector.start()
        try:
            if not completed.wait(timeout if timeout > 0 else None):
                try:
                    turn.interrupt()
                except Exception as error:
                    raise AxiError(
                        "turn_timeout",
                        f"Task {thread_id} exceeded {timeout:g} seconds and could not be "
                        "interrupted.",
                        f"Run `codex-axi task view {thread_id}` before retrying.",
                    ) from error
                raise AxiError(
                    "turn_timeout",
                    f"Task {thread_id} exceeded {timeout:g} seconds and was interrupted.",
                    f"Run `codex-axi task view {thread_id}` before retrying.",
                )
            if "error" in outcome:
                raise outcome["error"]
            return outcome["result"]
        finally:
            stop.set()
            relay_thread.join(timeout=1)
