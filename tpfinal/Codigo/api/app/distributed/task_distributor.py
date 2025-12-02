"""
Task Distribution System for ML Image Analysis.

Distributes image analysis tasks across nodes in the cluster using:
- Leader-based task assignment
- Load balancing (least loaded node)
- Lamport clock ordering
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class NodeLoad:
    """Track load for each node."""
    node_id: int
    pending_tasks: int = 0
    is_alive: bool = True


class TaskDistributor:
    """
    Distributed task assignment system.

    Leader node receives tasks and distributes them to available nodes.
    Uses least-loaded algorithm for load balancing.
    """

    def __init__(
        self,
        node_id: int,
        is_leader_callback: Callable[[], bool],
        get_alive_nodes_callback: Callable[[], list[int]],
        assign_task_rpc: Callable[[int, str, str, bytes], asyncio.Future],
    ):
        """
        Initialize task distributor.

        Args:
            node_id: This node's ID
            is_leader_callback: Function that returns True if this node is leader
            get_alive_nodes_callback: Function that returns list of alive node IDs
            assign_task_rpc: RPC function to assign task to another node
        """
        self.node_id = node_id
        self.is_leader = is_leader_callback
        self.get_alive_nodes = get_alive_nodes_callback
        self.assign_task_rpc = assign_task_rpc

        # Track load per node
        self.node_loads: dict[int, NodeLoad] = {}

        # Local task queue
        self.local_queue: asyncio.Queue = asyncio.Queue()
        self.processing = False

        logger.info(f"Node {node_id}: Task distributor initialized")

    async def submit_task(
        self,
        task_id: str,
        task_type: str,
        payload: bytes
    ) -> dict[str, any]:
        """
        Submit task for processing.

        If this is the leader:
        - Distribute to least loaded node
        If this is a follower:
        - Process locally or forward to leader

        Args:
            task_id: Unique task identifier
            task_type: Type of task (e.g., "analyze_image")
            payload: Task data (image bytes)

        Returns:
            Dict with task assignment info
        """
        if self.is_leader():
            # Leader distributes task
            target_node = self._select_node_for_task()
            logger.info(
                f"Node {self.node_id} (LEADER): Assigning task {task_id} to node {target_node}"
            )

            if target_node == self.node_id:
                # Assign to self
                await self.local_queue.put((task_id, task_type, payload))
                self._update_load(self.node_id, increment=1)
                return {
                    "assigned_to": self.node_id,
                    "status": "queued_local"
                }
            else:
                # Assign to another node via RPC
                response = await self.assign_task_rpc(
                    target_node,
                    task_id,
                    task_type,
                    payload
                )
                if response and response.get("accepted"):
                    self._update_load(target_node, increment=1)
                    return {
                        "assigned_to": target_node,
                        "status": "queued_remote"
                    }
                else:
                    # Fallback to local processing
                    logger.warning(
                        f"Node {self.node_id}: Failed to assign to {target_node}, "
                        "processing locally"
                    )
                    await self.local_queue.put((task_id, task_type, payload))
                    return {
                        "assigned_to": self.node_id,
                        "status": "queued_local_fallback"
                    }
        else:
            # Follower processes locally
            logger.info(
                f"Node {self.node_id} (FOLLOWER): Processing task {task_id} locally"
            )
            await self.local_queue.put((task_id, task_type, payload))
            return {
                "assigned_to": self.node_id,
                "status": "queued_local"
            }

    def _select_node_for_task(self) -> int:
        """
        Select best node for task using least-loaded algorithm.

        Returns:
            Node ID to assign task to
        """
        alive_nodes = self.get_alive_nodes()

        if not alive_nodes:
            logger.warning(f"Node {self.node_id}: No alive nodes, using self")
            return self.node_id

        # Initialize loads if needed
        for node_id in alive_nodes:
            if node_id not in self.node_loads:
                self.node_loads[node_id] = NodeLoad(node_id=node_id)

        # Find least loaded node
        least_loaded = min(
            (self.node_loads[nid] for nid in alive_nodes),
            key=lambda n: n.pending_tasks
        )

        logger.debug(
            f"Node {self.node_id}: Selected node {least_loaded.node_id} "
            f"with {least_loaded.pending_tasks} pending tasks"
        )

        return least_loaded.node_id

    def _update_load(self, node_id: int, increment: int) -> None:
        """Update load tracking for a node."""
        if node_id not in self.node_loads:
            self.node_loads[node_id] = NodeLoad(node_id=node_id)

        self.node_loads[node_id].pending_tasks += increment

        # Don't let it go negative
        if self.node_loads[node_id].pending_tasks < 0:
            self.node_loads[node_id].pending_tasks = 0

    async def get_next_task(self) -> tuple[str, str, bytes] | None:
        """
        Get next task from local queue.

        Returns:
            Tuple of (task_id, task_type, payload) or None if queue empty
        """
        try:
            task = await asyncio.wait_for(self.local_queue.get(), timeout=0.1)
            return task
        except asyncio.TimeoutError:
            return None

    def task_completed(self, node_id: int) -> None:
        """Mark task as completed on a node."""
        self._update_load(node_id, increment=-1)
        logger.debug(
            f"Node {self.node_id}: Task completed on node {node_id}, "
            f"remaining: {self.node_loads.get(node_id, NodeLoad(node_id)).pending_tasks}"
        )

    def get_load_summary(self) -> dict[int, int]:
        """Get summary of load across all nodes."""
        return {
            node_id: load.pending_tasks
            for node_id, load in self.node_loads.items()
        }
