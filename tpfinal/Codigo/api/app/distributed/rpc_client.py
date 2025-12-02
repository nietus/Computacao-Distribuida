"""
RPC Client for inter-node communication.

Provides client-side RPC calls to other nodes in the distributed system.
Uses HTTP/JSON for inter-node communication.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class RPCClient:
    """
    Simplified RPC client using HTTP/JSON (no gRPC dependency for now).

    In production, replace with gRPC implementation using node.proto.
    For academic purposes, this demonstrates the RPC pattern.
    """

    def __init__(self, node_id: int, node_addresses: dict[int, str]):
        """
        Initialize RPC client.

        Args:
            node_id: This node's ID
            node_addresses: Mapping of node_id -> "host:port"
        """
        self.node_id = node_id
        self.node_addresses = node_addresses
        self._session: aiohttp.ClientSession | None = None
        self._timeout = aiohttp.ClientTimeout(total=2.0)

        logger.info(f"RPC Client initialized for node {node_id}")
        logger.info(f"Known nodes: {node_addresses}")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    def get_node_address(self, target_node_id: int) -> str | None:
        """Get address for target node."""
        return self.node_addresses.get(target_node_id)

    async def ping(self, target_node_id: int, timestamp: int) -> dict[str, Any] | None:
        """
        Send ping/heartbeat to target node.

        Args:
            target_node_id: Node to ping
            timestamp: Lamport timestamp

        Returns:
            Response dict or None if failed
        """
        try:
            address = self.get_node_address(target_node_id)
            if not address:
                logger.warning(f"No address for node {target_node_id}")
                return None

            logger.debug(f"Node {self.node_id}: Pinging node {target_node_id} at {address}")

            # Extract host and port from address (format: "host:port")
            if ':' in address:
                host, port = address.rsplit(':', 1)
            else:
                host, port = address, '8000'

            url = f"http://{host}:{port}/v1/rpc/ping"
            session = await self._get_session()

            async with session.post(
                url,
                json={
                    "sender_id": self.node_id,
                    "timestamp": timestamp
                }
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.warning(f"Ping to node {target_node_id} returned status {response.status}")
                    return None

        except asyncio.TimeoutError:
            logger.debug(f"Node {self.node_id}: Ping timeout to {target_node_id}")
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
        Send election-related message (Bully algorithm).

        Args:
            target_node_id: Destination node
            message_type: "ELECTION", "OK", or "COORDINATOR"
            timestamp: Lamport timestamp

        Returns:
            True if successful
        """
        try:
            address = self.get_node_address(target_node_id)
            if not address:
                return False

            logger.debug(
                f"Node {self.node_id}: Sending {message_type} to {target_node_id}"
            )

            # Extract host and port
            if ':' in address:
                host, port = address.rsplit(':', 1)
            else:
                host, port = address, '8000'

            url = f"http://{host}:{port}/v1/rpc/election"
            session = await self._get_session()

            async with session.post(
                url,
                json={
                    "sender_id": self.node_id,
                    "message_type": message_type,
                    "timestamp": timestamp
                }
            ) as response:
                return response.status == 200

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
        Assign task to another node.

        Args:
            target_node_id: Node to assign task to
            task_id: Unique task identifier
            task_type: Type of task (e.g., "analyze_image")
            payload: Task data
            timestamp: Lamport timestamp

        Returns:
            Acknowledgement dict or None if failed
        """
        try:
            address = self.get_node_address(target_node_id)
            if not address:
                return None

            logger.info(
                f"Node {self.node_id}: Assigning task {task_id} to node {target_node_id}"
            )

            # Extract host and port
            if ':' in address:
                host, port = address.rsplit(':', 1)
            else:
                host, port = address, '8000'

            url = f"http://{host}:{port}/v1/rpc/task"
            session = await self._get_session()

            # Convert payload to base64 for JSON transport
            import base64
            payload_b64 = base64.b64encode(payload).decode('utf-8')

            async with session.post(
                url,
                json={
                    "sender_id": self.node_id,
                    "task_id": task_id,
                    "task_type": task_type,
                    "payload": payload_b64,
                    "timestamp": timestamp
                }
            ) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    return None

        except Exception as e:
            logger.error(
                f"Node {self.node_id}: Failed to assign task to {target_node_id}: {e}"
            )
            return None

    async def get_node_status(self, target_node_id: int) -> dict[str, Any] | None:
        """
        Query status of another node.

        Args:
            target_node_id: Node to query

        Returns:
            Status dict or None if failed
        """
        try:
            address = self.get_node_address(target_node_id)
            if not address:
                return None

            logger.debug(f"Node {self.node_id}: Querying status of node {target_node_id}")

            # Simulate RPC call
            await asyncio.sleep(0.01)
            return {
                "node_id": target_node_id,
                "is_leader": False,
                "status": "active"
            }

        except Exception as e:
            logger.error(
                f"Node {self.node_id}: Failed to get status from {target_node_id}: {e}"
            )
            return None

    async def close(self) -> None:
        """Close all connections."""
        logger.info(f"Node {self.node_id}: Closing RPC connections")
        if self._session and not self._session.closed:
            await self._session.close()
