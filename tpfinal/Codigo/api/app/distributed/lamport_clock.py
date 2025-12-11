"""
Implementação do Relógio Lógico de Lamport.

Implementa o algoritmo de Lamport para sincronização de relógios lógicos em sistemas distribuídos.
Referência: Lamport, L. (1978). "Time, Clocks, and the Ordering of Events in a Distributed System"
"""
from __future__ import annotations

import threading
from typing import Any


class LamportClock:
    """
    Relógio lógico de Lamport para ordenação de eventos em sistemas distribuídos.

    Propriedades:
    - Contador monotonicamente crescente
    - Operações thread-safe
    - Ordenação de eventos: se a -> b, então C(a) < C(b)
    """

    def __init__(self) -> None:
        self._counter: int = 0
        self._lock = threading.Lock()

    def time(self) -> int:
        """Retorna o valor atual do relógio."""
        with self._lock:
            return self._counter

    def tick(self) -> int:
        """
        Incrementa o relógio para evento interno.

        Retorna:
            Novo valor do relógio
        """
        with self._lock:
            self._counter += 1
            return self._counter

    def send_event(self) -> int:
        """
        Incrementa o relógio ao enviar uma mensagem.

        Retorna:
            Timestamp para anexar à mensagem
        """
        return self.tick()

    def receive_event(self, received_timestamp: int) -> int:
        """
        Atualiza o relógio ao receber uma mensagem.

        Regra de Lamport: C(i) = max(C(i), received_timestamp) + 1

        Args:
            received_timestamp: Timestamp da mensagem recebida

        Retorna:
            Novo valor do relógio local
        """
        with self._lock:
            self._counter = max(self._counter, received_timestamp) + 1
            return self._counter

    def __str__(self) -> str:
        return f"LamportClock(time={self.time()})"

    def __repr__(self) -> str:
        return self.__str__()
