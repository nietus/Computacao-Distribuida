"""
Lamport Logical Clock Implementation.

Implements Lamport's algorithm for logical clock synchronization in distributed systems.
Reference: Lamport, L. (1978). "Time, Clocks, and the Ordering of Events in a Distributed System"
"""
from __future__ import annotations

import threading
from typing import Any


class LamportClock:
    """
    Lamport logical clock for event ordering in distributed systems.

    Properties:
    - Monotonically increasing counter
    - Thread-safe operations
    - Event ordering: if a -> b, then C(a) < C(b)
    """

    def __init__(self) -> None:
        """Initialize clock with counter = 0."""
        self._counter: int = 0
        self._lock = threading.Lock()

    def time(self) -> int:
        """Get current clock value."""
        with self._lock:
            return self._counter

    def tick(self) -> int:
        """
        Increment clock for internal event.

        Returns:
            New clock value
        """
        with self._lock:
            self._counter += 1
            return self._counter

    def send_event(self) -> int:
        """
        Increment clock when sending a message.

        Returns:
            Timestamp to attach to message
        """
        return self.tick()

    def receive_event(self, received_timestamp: int) -> int:
        """
        Update clock when receiving a message.

        Lamport's rule: C(i) = max(C(i), received_timestamp) + 1

        Args:
            received_timestamp: Timestamp from received message

        Returns:
            New local clock value
        """
        with self._lock:
            self._counter = max(self._counter, received_timestamp) + 1
            return self._counter

    def __str__(self) -> str:
        """String representation."""
        return f"LamportClock(time={self.time()})"

    def __repr__(self) -> str:
        """Representation."""
        return self.__str__()
