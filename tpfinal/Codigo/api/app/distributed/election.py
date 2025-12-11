"""
Implementação do Algoritmo de Eleição Bully.

Implementa o algoritmo Bully para eleição de líder em sistemas distribuídos.
Referência: Garcia-Molina, H. (1982). "Elections in a Distributed Computing System"
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class NodeState(Enum):
    """Estado de participação do nó na eleição."""
    PARTICIPANT = "participant"
    LEADER = "leader"
    FOLLOWER = "follower"


@dataclass
class ElectionMessage:
    """Mensagem usada no algoritmo Bully."""
    sender_id: int
    message_type: str  # "ELECTION", "OK", "COORDINATOR"
    timestamp: int


class BullyElection:
    """
    Implementação do algoritmo de eleição Bully.

    Algoritmo:
    1. Quando um nó detecta falha do líder, inicia uma eleição
    2. Nó envia mensagem ELECTION para todos os nós com ID maior
    3. Se não houver resposta (OK) dentro do timeout, nó se torna líder
    4. Se receber OK, aguarda mensagem COORDINATOR
    5. Nó com maior ID vence e transmite mensagem COORDINATOR

    Propriedades:
    - Garante eleição eventual de líder
    - ID maior sempre vence
    - Trata eleições concorrentes
    """

    def __init__(
        self,
        node_id: int,
        all_node_ids: list[int],
        send_message_callback: Callable[[int, ElectionMessage], asyncio.Future],
        on_leader_change: Callable[[int], None] | None = None,
    ):
        """
        Inicializa o gerenciador de eleição Bully.

        Args:
            node_id: Identificador único deste nó
            all_node_ids: Lista de todos os IDs de nós no cluster
            send_message_callback: Função assíncrona para enviar mensagem a outro nó
            on_leader_change: Callback quando novo líder é eleito
        """
        self.node_id = node_id
        self.all_node_ids = sorted(all_node_ids)
        self.send_message = send_message_callback
        self.on_leader_change = on_leader_change

        self.state = NodeState.FOLLOWER
        self.current_leader: int | None = None
        self.election_in_progress = False
        self.received_ok = False

        self._lock = asyncio.Lock()

        self.election_timeout = 3.0
        self.coordinator_timeout = 5.0

        logger.info(f"Node {node_id} initialized with nodes: {all_node_ids}")

    @property
    def is_leader(self) -> bool:
        """Verifica se este nó é o líder atual."""
        return self.state == NodeState.LEADER

    @property
    def leader_id(self) -> int | None:
        """Retorna o ID do líder atual."""
        return self.current_leader

    def get_higher_nodes(self) -> list[int]:
        """Retorna lista de nós com ID maior que este."""
        return [nid for nid in self.all_node_ids if nid > self.node_id]

    async def start_election(self) -> None:
        """
        Inicia o processo de eleição (algoritmo Bully).

        Passos:
        1. Envia ELECTION para todos os nós com ID maior
        2. Aguarda respostas OK
        3. Se nenhum OK recebido, torna-se líder
        4. Se receber OK, aguarda COORDINATOR
        """
        async with self._lock:
            if self.election_in_progress:
                logger.debug(f"Node {self.node_id}: Election already in progress")
                return

            self.election_in_progress = True
            self.received_ok = False
            self.state = NodeState.PARTICIPANT

        logger.info(f"Node {self.node_id}: Starting election")

        higher_nodes = self.get_higher_nodes()

        if not higher_nodes:
            await self._become_leader()
            return

        election_msg = ElectionMessage(
            sender_id=self.node_id,
            message_type="ELECTION",
            timestamp=0
        )

        tasks = [self.send_message(nid, election_msg) for nid in higher_nodes]

        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.election_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"Node {self.node_id}: Election timeout")

        await asyncio.sleep(1.0)

        async with self._lock:
            got_ok = self.received_ok
            already_has_higher_leader = (
                self.current_leader is not None and
                self.current_leader > self.node_id
            )

        if already_has_higher_leader:
            logger.info(f"Node {self.node_id}: Higher node {self.current_leader} is already leader")
            async with self._lock:
                self.election_in_progress = False
                self.state = NodeState.FOLLOWER
            return

        if not got_ok:
            await self._become_leader()
        else:
            logger.info(f"Node {self.node_id}: Received OK, waiting for COORDINATOR")
            async with self._lock:
                self.election_in_progress = False
            await self._wait_for_coordinator()

    async def _become_leader(self) -> None:
        """Transiciona para estado de líder e transmite COORDINATOR."""
        async with self._lock:
            if self.current_leader is not None and self.current_leader > self.node_id:
                logger.info(
                    f"Node {self.node_id}: Aborting leadership claim, "
                    f"higher node {self.current_leader} is already leader"
                )
                self.state = NodeState.FOLLOWER
                self.election_in_progress = False
                return

            self.state = NodeState.LEADER
            self.current_leader = self.node_id
            self.election_in_progress = False

        logger.info(f"Node {self.node_id}: I AM THE NEW LEADER!")

        coordinator_msg = ElectionMessage(
            sender_id=self.node_id,
            message_type="COORDINATOR",
            timestamp=0
        )

        tasks = [
            self.send_message(nid, coordinator_msg)
            for nid in self.all_node_ids
            if nid != self.node_id
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        if self.on_leader_change:
            self.on_leader_change(self.node_id)

    async def _wait_for_coordinator(self) -> None:
        """Aguarda mensagem COORDINATOR do novo líder."""
        try:
            await asyncio.sleep(self.coordinator_timeout)

            if self.current_leader is None or self.current_leader == self.node_id:
                logger.warning(f"Node {self.node_id}: No COORDINATOR received, restarting election")
                async with self._lock:
                    self.election_in_progress = False
                await self.start_election()
        except Exception as e:
            logger.error(f"Node {self.node_id}: Error waiting for coordinator: {e}")

    async def handle_election_message(self, msg: ElectionMessage) -> None:
        """
        Processa mensagem ELECTION recebida.

        Resposta: Envia OK e inicia própria eleição se necessário.
        """
        logger.info(f"Node {self.node_id}: Received ELECTION from {msg.sender_id}")

        ok_msg = ElectionMessage(
            sender_id=self.node_id,
            message_type="OK",
            timestamp=0
        )
        await self.send_message(msg.sender_id, ok_msg)

        if not self.election_in_progress and msg.sender_id < self.node_id:
            asyncio.create_task(self.start_election())

    async def handle_ok_message(self, msg: ElectionMessage) -> None:
        """Processa mensagem OK recebida."""
        logger.info(f"Node {self.node_id}: Received OK from {msg.sender_id}")
        self.received_ok = True

    async def handle_coordinator_message(self, msg: ElectionMessage) -> None:
        """Processa mensagem COORDINATOR recebida (anúncio de novo líder)."""
        if msg.sender_id < self.node_id:
            logger.warning(
                f"Node {self.node_id}: Rejecting COORDINATOR from lower node {msg.sender_id}, "
                "I have higher ID so I should be leader"
            )
            async with self._lock:
                if not self.election_in_progress:
                    self.election_in_progress = False
            asyncio.create_task(self.start_election())
            return

        logger.info(f"Node {self.node_id}: Accepting node {msg.sender_id} as new leader")

        async with self._lock:
            self.current_leader = msg.sender_id
            self.state = NodeState.FOLLOWER
            self.election_in_progress = False
            self.received_ok = False

        if self.on_leader_change:
            self.on_leader_change(msg.sender_id)

    async def handle_message(self, msg: ElectionMessage) -> None:
        """Roteia mensagens de eleição recebidas para o handler apropriado."""
        if msg.message_type == "ELECTION":
            await self.handle_election_message(msg)
        elif msg.message_type == "OK":
            await self.handle_ok_message(msg)
        elif msg.message_type == "COORDINATOR":
            await self.handle_coordinator_message(msg)
        else:
            logger.warning(f"Node {self.node_id}: Unknown message type {msg.message_type}")
