"""
Bully Election Algorithm Implementation.

Implements the Bully algorithm for leader election in distributed systems.
Reference: Garcia-Molina, H. (1982). "Elections in a Distributed Computing System"
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class NodeState(Enum):
    """Node participation state in election."""
    PARTICIPANT = "participant"
    LEADER = "leader"
    FOLLOWER = "follower"


@dataclass
class ElectionMessage:
    """Message used in Bully algorithm."""
    sender_id: int
    message_type: str  # "ELECTION", "OK", "COORDINATOR"
    timestamp: int


class BullyElection:
    """
    Bully Election Algorithm implementation.

    Algorithm:
    1. When a node detects leader failure, it starts an election
    2. Node sends ELECTION message to all nodes with higher ID
    3. If no response (OK) within timeout, node becomes leader
    4. If receives OK, waits for COORDINATOR message
    5. Node with highest ID wins and broadcasts COORDINATOR message

    Properties:
    - Ensures eventual leader election
    - Higher ID always wins
    - Handles concurrent elections
    """

    def __init__(
        self,
        node_id: int,
        all_node_ids: list[int],
        send_message_callback: Callable[[int, ElectionMessage], asyncio.Future],
        on_leader_change: Callable[[int], None] | None = None,
    ):
        """
        Initialize Bully election manager.

        Args:
            node_id: This node's unique identifier
            all_node_ids: List of all node IDs in cluster
            send_message_callback: Async function to send message to another node
            on_leader_change: Callback when new leader is elected
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

        # Timeouts (in seconds)
        self.election_timeout = 3.0
        self.coordinator_timeout = 5.0

        logger.info(f"Node {node_id} initialized with nodes: {all_node_ids}")

    @property
    def is_leader(self) -> bool:
        """Check if this node is the current leader."""
        return self.state == NodeState.LEADER

    @property
    def leader_id(self) -> int | None:
        """Get current leader ID."""
        return self.current_leader

    def get_higher_nodes(self) -> list[int]:
        """Get list of nodes with higher ID than self."""
        return [nid for nid in self.all_node_ids if nid > self.node_id]

    async def start_election(self) -> None:
        """
        Start election process (Bully algorithm).

        Steps:
        1. Send ELECTION to all higher-ID nodes
        2. Wait for OK responses
        3. If no OK received, become leader
        4. If OK received, wait for COORDINATOR
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
            # No higher nodes, I am the leader!
            await self._become_leader()
            return

        # Send ELECTION to all higher nodes
        election_msg = ElectionMessage(
            sender_id=self.node_id,
            message_type="ELECTION",
            timestamp=0  # Will be set by Lamport clock in actual usage
        )

        # Send to all higher nodes concurrently
        tasks = [self.send_message(nid, election_msg) for nid in higher_nodes]

        # Wait for responses with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.election_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"Node {self.node_id}: Election timeout")

        # Wait a bit for OK responses to arrive
        await asyncio.sleep(0.5)

        if not self.received_ok:
            # No higher node responded, I win!
            await self._become_leader()
        else:
            # Wait for COORDINATOR message
            logger.info(f"Node {self.node_id}: Received OK, waiting for COORDINATOR")
            await self._wait_for_coordinator()

    async def _become_leader(self) -> None:
        """Transition to leader state and broadcast COORDINATOR."""
        async with self._lock:
            self.state = NodeState.LEADER
            self.current_leader = self.node_id
            self.election_in_progress = False

        logger.info(f"Node {self.node_id}: I AM THE NEW LEADER!")

        # Broadcast COORDINATOR to all nodes
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
        """Wait for COORDINATOR message from new leader."""
        try:
            await asyncio.sleep(self.coordinator_timeout)

            # If still no leader after timeout, restart election
            if self.current_leader is None or self.current_leader == self.node_id:
                logger.warning(f"Node {self.node_id}: No COORDINATOR received, restarting election")
                async with self._lock:
                    self.election_in_progress = False
                await self.start_election()
        except Exception as e:
            logger.error(f"Node {self.node_id}: Error waiting for coordinator: {e}")

    async def handle_election_message(self, msg: ElectionMessage) -> None:
        """
        Handle incoming ELECTION message.

        Response: Send OK and start own election if necessary.
        """
        logger.info(f"Node {self.node_id}: Received ELECTION from {msg.sender_id}")

        # Always respond OK to lower-ID nodes
        ok_msg = ElectionMessage(
            sender_id=self.node_id,
            message_type="OK",
            timestamp=0
        )
        await self.send_message(msg.sender_id, ok_msg)

        # Start own election if not already in progress
        if not self.election_in_progress and msg.sender_id < self.node_id:
            asyncio.create_task(self.start_election())

    async def handle_ok_message(self, msg: ElectionMessage) -> None:
        """Handle incoming OK message."""
        logger.info(f"Node {self.node_id}: Received OK from {msg.sender_id}")
        self.received_ok = True

    async def handle_coordinator_message(self, msg: ElectionMessage) -> None:
        """Handle incoming COORDINATOR message (new leader announcement)."""
        logger.info(f"Node {self.node_id}: New leader is {msg.sender_id}")

        async with self._lock:
            self.current_leader = msg.sender_id
            self.state = NodeState.FOLLOWER
            self.election_in_progress = False

        if self.on_leader_change:
            self.on_leader_change(msg.sender_id)

    async def handle_message(self, msg: ElectionMessage) -> None:
        """Route incoming election messages to appropriate handler."""
        if msg.message_type == "ELECTION":
            await self.handle_election_message(msg)
        elif msg.message_type == "OK":
            await self.handle_ok_message(msg)
        elif msg.message_type == "COORDINATOR":
            await self.handle_coordinator_message(msg)
        else:
            logger.warning(f"Node {self.node_id}: Unknown message type {msg.message_type}")
