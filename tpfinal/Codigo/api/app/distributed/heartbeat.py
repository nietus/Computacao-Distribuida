"""
Fault Tolerance with Heartbeat Monitoring.

Implements failure detection using periodic heartbeats between nodes.
Triggers leader election when leader failure is detected.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class NodeHealth:
    """Health information for a node."""
    node_id: int
    last_heartbeat: float
    is_alive: bool = True
    consecutive_failures: int = 0


class HeartbeatMonitor:
    """
    Heartbeat-based failure detection.

    Properties:
    - Periodic ping to all nodes
    - Tracks last successful heartbeat
    - Declares node failed after N consecutive timeouts
    - Triggers callbacks on node failure/recovery
    """

    def __init__(
        self,
        node_id: int,
        all_node_ids: list[int],
        ping_callback: Callable[[int], asyncio.Future[bool]],
        on_node_failed: Callable[[int], None] | None = None,
        on_node_recovered: Callable[[int], None] | None = None,
        on_leader_failed: Callable[[], None] | None = None,
    ):
        """
        Initialize heartbeat monitor.

        Args:
            node_id: This node's ID
            all_node_ids: All nodes in cluster
            ping_callback: Async function to ping another node, returns success bool
            on_node_failed: Callback when node declared failed
            on_node_recovered: Callback when failed node recovers
            on_leader_failed: Callback when leader fails (triggers election)
        """
        self.node_id = node_id
        self.all_node_ids = [nid for nid in all_node_ids if nid != node_id]
        self.ping_callback = ping_callback
        self.on_node_failed = on_node_failed
        self.on_node_recovered = on_node_recovered
        self.on_leader_failed = on_leader_failed

        # Health tracking
        self.node_health: dict[int, NodeHealth] = {
            nid: NodeHealth(node_id=nid, last_heartbeat=time.time())
            for nid in self.all_node_ids
        }

        # Configuration
        self.heartbeat_interval = 2.0  # seconds between heartbeats
        self.failure_threshold = 3  # consecutive failures to declare dead
        self.timeout = 1.5  # seconds to wait for ping response

        # State
        self.current_leader_id: int | None = None
        self.running = False
        self._monitor_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

        logger.info(
            f"Node {node_id}: Heartbeat monitor initialized, "
            f"monitoring {len(self.all_node_ids)} nodes"
        )

    def set_leader(self, leader_id: int) -> None:
        """Update current leader ID."""
        self.current_leader_id = leader_id
        logger.info(f"Node {self.node_id}: Leader set to {leader_id}")

    async def start(self) -> None:
        """Start heartbeat monitoring."""
        if self.running:
            logger.warning(f"Node {self.node_id}: Heartbeat monitor already running")
            return

        self.running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Node {self.node_id}: Heartbeat monitor started")

    async def stop(self) -> None:
        """Stop heartbeat monitoring."""
        self.running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info(f"Node {self.node_id}: Heartbeat monitor stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        logger.info(f"Node {self.node_id}: Starting heartbeat loop")

        while self.running:
            try:
                await self._send_heartbeats()
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Node {self.node_id}: Error in heartbeat loop: {e}")
                await asyncio.sleep(1.0)

    async def _send_heartbeats(self) -> None:
        """Send heartbeat to all nodes and check responses."""
        tasks = [self._ping_node(nid) for nid in self.all_node_ids]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _ping_node(self, target_node_id: int) -> None:
        """
        Ping a specific node and update health status.

        Args:
            target_node_id: Node to ping
        """
        try:
            # Send ping with timeout
            success = await asyncio.wait_for(
                self.ping_callback(target_node_id),
                timeout=self.timeout
            )

            async with self._lock:
                health = self.node_health[target_node_id]

                if success:
                    # Successful heartbeat
                    health.last_heartbeat = time.time()
                    health.consecutive_failures = 0

                    # Check if node recovered
                    if not health.is_alive:
                        logger.info(f"Node {self.node_id}: Node {target_node_id} RECOVERED")
                        health.is_alive = True
                        if self.on_node_recovered:
                            self.on_node_recovered(target_node_id)
                else:
                    # Failed heartbeat
                    health.consecutive_failures += 1
                    logger.warning(
                        f"Node {self.node_id}: Ping to {target_node_id} failed "
                        f"({health.consecutive_failures}/{self.failure_threshold})"
                    )

                    # Check if node should be declared failed
                    if (
                        health.consecutive_failures >= self.failure_threshold
                        and health.is_alive
                    ):
                        logger.error(f"Node {self.node_id}: Node {target_node_id} DECLARED FAILED")
                        health.is_alive = False

                        # Trigger failure callbacks
                        if self.on_node_failed:
                            self.on_node_failed(target_node_id)

                        # Check if leader failed
                        if target_node_id == self.current_leader_id:
                            logger.critical(
                                f"Node {self.node_id}: LEADER {target_node_id} FAILED! "
                                "Triggering election..."
                            )
                            if self.on_leader_failed:
                                self.on_leader_failed()

        except asyncio.TimeoutError:
            async with self._lock:
                health = self.node_health[target_node_id]
                health.consecutive_failures += 1
                logger.warning(
                    f"Node {self.node_id}: Ping to {target_node_id} TIMEOUT "
                    f"({health.consecutive_failures}/{self.failure_threshold})"
                )

        except Exception as e:
            logger.error(f"Node {self.node_id}: Error pinging {target_node_id}: {e}")

    def get_alive_nodes(self) -> list[int]:
        """Get list of currently alive nodes (including self)."""
        alive = [self.node_id]  # Include self
        for nid, health in self.node_health.items():
            if health.is_alive:
                alive.append(nid)
        return sorted(alive)

    def is_node_alive(self, node_id: int) -> bool:
        """Check if a specific node is alive."""
        if node_id == self.node_id:
            return True
        health = self.node_health.get(node_id)
        return health.is_alive if health else False

    def get_health_summary(self) -> dict[int, dict]:
        """Get summary of all node health statuses."""
        summary = {}
        for nid, health in self.node_health.items():
            summary[nid] = {
                "is_alive": health.is_alive,
                "last_heartbeat": health.last_heartbeat,
                "time_since_heartbeat": time.time() - health.last_heartbeat,
                "consecutive_failures": health.consecutive_failures
            }
        return summary
