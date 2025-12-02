"""
Distributed Node Manager.

Orchestrates all distributed systems components:
- Lamport logical clocks
- Bully election algorithm
- RPC communication
- Heartbeat-based failure detection
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable

from .election import BullyElection, ElectionMessage
from .heartbeat import HeartbeatMonitor
from .lamport_clock import LamportClock
from .rpc_client import RPCClient
from .task_distributor import TaskDistributor

# Import gRPC client (optional)
try:
    from .rpc_client_grpc import GRPCClient
    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    GRPCClient = None

logger = logging.getLogger(__name__)


class DistributedNode:
    """
    Main distributed node manager.

    Integrates all distributed systems algorithms and provides
    high-level interface for the application layer.
    """

    def __init__(
        self,
        node_id: int,
        node_addresses: dict[int, str],
        on_task_assigned: Callable[[str, bytes], asyncio.Future] | None = None,
        use_grpc: bool = False
    ):
        """
        Initialize distributed node.

        Args:
            node_id: Unique identifier for this node (1, 2, 3)
            node_addresses: Mapping of node_id -> "host:port" (or "host:grpc_port" if use_grpc=True)
            on_task_assigned: Callback when task is assigned to this node
            use_grpc: If True, use gRPC instead of HTTP/JSON for RPC (default: False)
        """
        self.node_id = node_id
        self.node_addresses = node_addresses
        self.all_node_ids = list(node_addresses.keys())
        self.on_task_assigned = on_task_assigned
        self.on_task_assigned_tensorflow = None  # Callback for TensorFlow tasks
        self.use_grpc = use_grpc
        self.grpc_server = None  # Will hold gRPC server instance

        # Initialize components
        self.clock = LamportClock()

        # Choose RPC implementation
        if use_grpc and GRPC_AVAILABLE:
            logger.info(f"Node {node_id}: Using gRPC for inter-node communication")
            self.rpc_client = GRPCClient(node_id, node_addresses)
        else:
            if use_grpc:
                logger.warning(f"Node {node_id}: gRPC requested but not available, falling back to HTTP")
            logger.info(f"Node {node_id}: Using HTTP/JSON for inter-node communication")
            self.rpc_client = RPCClient(node_id, node_addresses)

        # Initialize Bully election
        self.election = BullyElection(
            node_id=node_id,
            all_node_ids=self.all_node_ids,
            send_message_callback=self._send_election_message,
            on_leader_change=self._on_leader_change
        )

        # Initialize heartbeat monitor
        self.heartbeat = HeartbeatMonitor(
            node_id=node_id,
            all_node_ids=self.all_node_ids,
            ping_callback=self._ping_node,
            on_node_failed=self._on_node_failed,
            on_node_recovered=self._on_node_recovered,
            on_leader_failed=self._on_leader_failed
        )

        # Task distributor
        self.task_distributor = TaskDistributor(
            node_id=node_id,
            is_leader_callback=lambda: self.is_leader,
            get_alive_nodes_callback=lambda: self.heartbeat.get_alive_nodes(),
            assign_task_rpc=self._assign_task_via_rpc
        )

        # State
        self.running = False
        self.tasks_processed = 0
        self.tasks_queue: asyncio.Queue = asyncio.Queue()

        logger.info(
            f"Node {node_id}: Initialized distributed node with addresses {node_addresses}"
        )

    @property
    def is_leader(self) -> bool:
        """Check if this node is the current leader."""
        return self.election.is_leader

    @property
    def leader_id(self) -> int | None:
        """Get current leader ID."""
        return self.election.leader_id

    async def start(self) -> None:
        """Start the distributed node."""
        if self.running:
            logger.warning(f"Node {self.node_id}: Already running")
            return

        self.running = True
        logger.info(f"Node {self.node_id}: Starting distributed node...")

        # Start gRPC server if using gRPC
        if self.use_grpc and GRPC_AVAILABLE:
            from .grpc_server import serve_grpc
            grpc_port = int(os.getenv("GRPC_PORT", "50051"))
            self.grpc_server = await serve_grpc(self, port=grpc_port)
            logger.info(f"Node {self.node_id}: gRPC server started on port {grpc_port}")

        # Start heartbeat monitoring
        await self.heartbeat.start()

        # Wait a bit for heartbeats to stabilize
        await asyncio.sleep(1.0)

        # Start election to determine leader
        logger.info(f"Node {self.node_id}: Starting initial leader election...")
        await self.election.start_election()

        # Start task processing loop (if needed)
        asyncio.create_task(self._process_tasks())

        logger.info(
            f"Node {self.node_id}: Started successfully. "
            f"Leader: {self.leader_id}, Clock: {self.clock.time()}"
        )

    async def stop(self) -> None:
        """Stop the distributed node."""
        logger.info(f"Node {self.node_id}: Stopping...")
        self.running = False
        await self.heartbeat.stop()
        await self.rpc_client.close()

        # Stop gRPC server if running
        if self.grpc_server:
            logger.info(f"Node {self.node_id}: Stopping gRPC server...")
            await self.grpc_server.stop(grace=2.0)
            self.grpc_server = None

        logger.info(f"Node {self.node_id}: Stopped")

    async def submit_image_analysis(
        self,
        task_id: str,
        image_bytes: bytes
    ) -> dict[str, Any]:
        """
        Submit image analysis task to distributed system (PyTorch).

        Leader distributes to least-loaded node.
        Follower processes locally.

        Args:
            task_id: Unique task identifier
            image_bytes: Image data

        Returns:
            Assignment info dict
        """
        return await self.task_distributor.submit_task(
            task_id=task_id,
            task_type="analyze_image",
            payload=image_bytes
        )

    async def submit_image_analysis_tensorflow(
        self,
        task_id: str,
        image_bytes: bytes
    ) -> dict[str, Any]:
        """
        Submit image analysis task to distributed system (TensorFlow).

        Leader distributes to least-loaded node.
        Follower processes locally.

        Args:
            task_id: Unique task identifier
            image_bytes: Image data

        Returns:
            Assignment info dict
        """
        return await self.task_distributor.submit_task(
            task_id=task_id,
            task_type="analyze_image_tensorflow",
            payload=image_bytes
        )

    async def _assign_task_via_rpc(
        self,
        target_node_id: int,
        task_id: str,
        task_type: str,
        payload: bytes
    ) -> dict[str, Any] | None:
        """Assign task to another node via RPC."""
        timestamp = self.clock.send_event()
        return await self.rpc_client.assign_task(
            target_node_id,
            task_id,
            task_type,
            payload,
            timestamp
        )

    def get_status(self) -> dict[str, Any]:
        """Get current node status."""
        alive_nodes = self.heartbeat.get_alive_nodes()
        health_summary = self.heartbeat.get_health_summary()
        load_summary = self.task_distributor.get_load_summary()

        return {
            "node_id": self.node_id,
            "is_leader": self.is_leader,
            "leader_id": self.leader_id,
            "lamport_clock": self.clock.time(),
            "election_state": self.election.state.value,
            "alive_nodes": alive_nodes,
            "total_nodes": len(self.all_node_ids),
            "tasks_processed": self.tasks_processed,
            "health_summary": health_summary,
            "load_summary": load_summary
        }

    # RPC message handlers (called by RPC server)

    async def handle_election_message(self, msg: ElectionMessage) -> None:
        """Handle incoming election message."""
        # Update Lamport clock
        self.clock.receive_event(msg.timestamp)
        # Pass to election module
        await self.election.handle_message(msg)

    async def handle_task_assignment(
        self,
        task_id: str,
        task_type: str,
        payload: bytes
    ) -> dict[str, Any]:
        """
        Handle task assignment from leader.

        Args:
            task_id: Unique task identifier
            task_type: Type of task
            payload: Task data

        Returns:
            Acknowledgement dict
        """
        logger.info(f"Node {self.node_id}: Received task assignment {task_id}")

        try:
            # Add to processing queue
            await self.tasks_queue.put((task_id, task_type, payload))

            return {
                "task_id": task_id,
                "accepted": True,
                "message": f"Task queued on node {self.node_id}"
            }
        except Exception as e:
            logger.error(f"Node {self.node_id}: Failed to accept task {task_id}: {e}")
            return {
                "task_id": task_id,
                "accepted": False,
                "message": str(e)
            }

    # Internal methods

    async def _send_election_message(
        self,
        target_node_id: int,
        msg: ElectionMessage
    ) -> None:
        """Send election message via RPC."""
        msg.timestamp = self.clock.send_event()
        await self.rpc_client.send_election_message(
            target_node_id,
            msg.message_type,
            msg.timestamp
        )

    async def _ping_node(self, target_node_id: int) -> bool:
        """Ping another node (used by heartbeat monitor)."""
        timestamp = self.clock.send_event()
        response = await self.rpc_client.ping(target_node_id, timestamp)

        if response:
            self.clock.receive_event(response.get("timestamp", timestamp))
            return True
        return False

    def _on_leader_change(self, new_leader_id: int) -> None:
        """Callback when leader changes."""
        logger.info(f"Node {self.node_id}: Leader changed to {new_leader_id}")
        self.heartbeat.set_leader(new_leader_id)

    def _on_node_failed(self, failed_node_id: int) -> None:
        """Callback when a node fails."""
        logger.warning(f"Node {self.node_id}: Node {failed_node_id} declared failed")
        # Could trigger task reassignment, etc.

    def _on_node_recovered(self, recovered_node_id: int) -> None:
        """Callback when a failed node recovers."""
        logger.info(f"Node {self.node_id}: Node {recovered_node_id} recovered")

    async def _on_leader_failed(self) -> None:
        """Callback when leader fails - trigger new election."""
        logger.critical(f"Node {self.node_id}: Leader failed! Starting new election...")
        await self.election.start_election()

    async def _process_tasks(self) -> None:
        """Background task processing loop."""
        logger.info(f"Node {self.node_id}: Task processing loop started")

        while self.running:
            try:
                # Get task from distributor queue
                task_data = await self.task_distributor.get_next_task()

                if task_data is None:
                    await asyncio.sleep(0.1)
                    continue

                task_id, task_type, payload = task_data

                logger.info(
                    f"Node {self.node_id}: Processing task {task_id} (type: {task_type})"
                )

                if task_type in ("analyze_image", "analyze_image_tensorflow"):
                    if self.on_task_assigned:
                        if task_type == "analyze_image_tensorflow":
                            await self.on_task_assigned_tensorflow(task_id, payload)
                        else:
                            await self.on_task_assigned(task_id, payload)
                else:
                    if self.on_task_assigned:
                        await self.on_task_assigned(task_id, payload)

                self.tasks_processed += 1
                self.task_distributor.task_completed(self.node_id)

                logger.info(f"Node {self.node_id}: Task {task_id} completed")

            except Exception as e:
                logger.error(f"Node {self.node_id}: Error processing task: {e}")
                await asyncio.sleep(0.5)


# Utility function to create node from environment
def create_node_from_env() -> DistributedNode:
    """
    Create DistributedNode from environment variables.

    Expected env vars:
    - NODE_ID: This node's ID (1, 2, or 3)
    - NODE_1_ADDRESS: Address of node 1 (e.g., "node1:8000" for HTTP or "node1:50051" for gRPC)
    - NODE_2_ADDRESS: Address of node 2
    - NODE_3_ADDRESS: Address of node 3
    - USE_GRPC: "true" to enable gRPC, "false" for HTTP/JSON (default: false)
    - GRPC_PORT: gRPC port to listen on (default: 50051)
    """
    node_id = int(os.getenv("NODE_ID", "1"))
    use_grpc = os.getenv("USE_GRPC", "false").lower() == "true"

    # Node addresses depend on protocol
    if use_grpc:
        # For gRPC, use gRPC ports
        node_addresses = {
            1: os.getenv("NODE_1_ADDRESS", "node1:50051"),
            2: os.getenv("NODE_2_ADDRESS", "node2:50051"),
            3: os.getenv("NODE_3_ADDRESS", "node3:50051"),
        }
    else:
        # For HTTP, use HTTP ports
        node_addresses = {
            1: os.getenv("NODE_1_ADDRESS", "node1:8000"),
            2: os.getenv("NODE_2_ADDRESS", "node2:8000"),
            3: os.getenv("NODE_3_ADDRESS", "node3:8000"),
        }

    logger.info(
        f"Creating node {node_id} with addresses: {node_addresses}, "
        f"using {'gRPC' if use_grpc else 'HTTP/JSON'}"
    )

    return DistributedNode(node_id=node_id, node_addresses=node_addresses, use_grpc=use_grpc)
