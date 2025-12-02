"""
gRPC-based RPC Client for inter-node communication.

This is the production implementation using gRPC instead of HTTP/JSON.
Provides better performance with binary protocol buffers.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import grpc

# Import generated protobuf classes
from . import node_pb2
from . import node_pb2_grpc

logger = logging.getLogger(__name__)


class GRPCClient:
    """
    Production RPC client using gRPC with Protocol Buffers.

    Provides efficient binary communication between distributed nodes.
    """

    def __init__(self, node_id: int, node_addresses: dict[int, str]):
        """
        Initialize gRPC client.

        Args:
            node_id: This node's ID
            node_addresses: Mapping of node_id -> "host:port" (gRPC ports)
        """
        self.node_id = node_id
        self.node_addresses = node_addresses
        self._channels: dict[int, grpc.aio.Channel] = {}
        self._stubs: dict[int, node_pb2_grpc.NodeServiceStub] = {}

        logger.info(f"gRPC Client initialized for node {node_id}")
        logger.info(f"Known nodes: {node_addresses}")

    async def _get_stub(self, target_node_id: int) -> node_pb2_grpc.NodeServiceStub | None:
        """Get or create gRPC stub for target node."""
        if target_node_id not in self._stubs:
            address = self.node_addresses.get(target_node_id)
            if not address:
                logger.warning(f"No address for node {target_node_id}")
                return None

            # Create channel and stub
            channel = grpc.aio.insecure_channel(address)
            self._channels[target_node_id] = channel
            self._stubs[target_node_id] = node_pb2_grpc.NodeServiceStub(channel)
            logger.debug(f"Created gRPC channel to node {target_node_id} at {address}")

        return self._stubs[target_node_id]

    def get_node_address(self, target_node_id: int) -> str | None:
        """Get address for target node."""
        return self.node_addresses.get(target_node_id)

    async def ping(self, target_node_id: int, timestamp: int) -> dict[str, Any] | None:
        """
        Send ping/heartbeat to target node via gRPC.

        Args:
            target_node_id: Node to ping
            timestamp: Lamport timestamp

        Returns:
            Response dict or None if failed
        """
        try:
            stub = await self._get_stub(target_node_id)
            if not stub:
                return None

            logger.debug(f"Node {self.node_id}: Pinging node {target_node_id} via gRPC")

            # Create protobuf request
            request = node_pb2.PingRequest(
                sender_id=self.node_id,
                timestamp=timestamp
            )

            # Make gRPC call with timeout
            response = await asyncio.wait_for(
                stub.Ping(request),
                timeout=1.5
            )

            return {
                "node_id": response.responder_id,
                "status": response.status,
                "timestamp": response.timestamp
            }

        except asyncio.TimeoutError:
            logger.debug(f"Node {self.node_id}: gRPC ping timeout to {target_node_id}")
            return None
        except grpc.RpcError as e:
            logger.debug(f"Node {self.node_id}: gRPC error pinging {target_node_id}: {e.code()}")
            return None
        except Exception as e:
            logger.debug(f"Node {self.node_id}: Failed to ping {target_node_id}: {e}")
            return None

    async def send_election_message(
        self,
        target_node_id: int,
        message_type: str,
        timestamp: int
    ) -> bool:
        """
        Send election-related message via gRPC (Bully algorithm).

        Args:
            target_node_id: Destination node
            message_type: "ELECTION", "OK", or "COORDINATOR"
            timestamp: Lamport timestamp

        Returns:
            True if successful
        """
        try:
            stub = await self._get_stub(target_node_id)
            if not stub:
                return False

            logger.debug(
                f"Node {self.node_id}: Sending {message_type} to {target_node_id} via gRPC"
            )

            # Create protobuf request
            request = node_pb2.ElectionRequest(
                sender_id=self.node_id,
                message_type=message_type,
                timestamp=timestamp
            )

            # Make gRPC call with timeout
            response = await asyncio.wait_for(
                stub.SendElection(request),
                timeout=2.0
            )

            return response.acknowledged

        except Exception as e:
            logger.debug(
                f"Node {self.node_id}: Failed to send {message_type} to {target_node_id}: {e}"
            )
            return False

    async def assign_task(
        self,
        target_node_id: int,
        task_id: str,
        task_type: str,
        payload: bytes,
        timestamp: int
    ) -> dict[str, Any] | None:
        """
        Assign task to another node via gRPC.

        Args:
            target_node_id: Node to assign task to
            task_id: Unique task identifier
            task_type: Type of task (e.g., "analyze_image")
            payload: Task data (binary)
            timestamp: Lamport timestamp

        Returns:
            Acknowledgement dict or None if failed
        """
        try:
            stub = await self._get_stub(target_node_id)
            if not stub:
                return None

            logger.info(
                f"Node {self.node_id}: Assigning task {task_id} to node {target_node_id} via gRPC"
            )

            # Create protobuf request (payload is already bytes)
            request = node_pb2.TaskAssignment(
                task_id=task_id,
                task_type=task_type,
                payload=payload,
                timestamp=timestamp,
                assigned_by=self.node_id
            )

            # Make gRPC call with timeout
            response = await asyncio.wait_for(
                stub.AssignTask(request),
                timeout=3.0
            )

            return {
                "task_id": response.task_id,
                "accepted": response.accepted,
                "message": response.message
            }

        except Exception as e:
            logger.error(
                f"Node {self.node_id}: Failed to assign task to {target_node_id}: {e}"
            )
            return None

    async def get_node_status(self, target_node_id: int) -> dict[str, Any] | None:
        """
        Query status of another node via gRPC.

        Args:
            target_node_id: Node to query

        Returns:
            Status dict or None if failed
        """
        try:
            stub = await self._get_stub(target_node_id)
            if not stub:
                return None

            logger.debug(f"Node {self.node_id}: Querying status of node {target_node_id} via gRPC")

            # Create protobuf request
            request = node_pb2.StatusRequest(sender_id=self.node_id)

            # Make gRPC call with timeout
            response = await asyncio.wait_for(
                stub.GetStatus(request),
                timeout=2.0
            )

            return {
                "node_id": response.node_id,
                "is_leader": response.is_leader,
                "leader_id": response.leader_id,
                "lamport_clock": response.lamport_clock,
                "active_nodes": list(response.active_nodes),
                "pending_tasks": response.pending_tasks,
                "hardware_info": response.hardware_info
            }

        except Exception as e:
            logger.error(
                f"Node {self.node_id}: Failed to get status from {target_node_id}: {e}"
            )
            return None

    async def close(self) -> None:
        """Close all gRPC channels."""
        logger.info(f"Node {self.node_id}: Closing gRPC connections")
        for node_id, channel in self._channels.items():
            await channel.close()
            logger.debug(f"Closed gRPC channel to node {node_id}")

        self._channels.clear()
        self._stubs.clear()
