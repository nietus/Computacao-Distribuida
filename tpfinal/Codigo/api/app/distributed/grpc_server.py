"""
gRPC Server implementation for distributed node communication.

Implements the NodeService defined in node.proto.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import grpc

from . import node_pb2
from . import node_pb2_grpc

if TYPE_CHECKING:
    from .node_manager import DistributedNode

logger = logging.getLogger(__name__)


class NodeServiceServicer(node_pb2_grpc.NodeServiceServicer):
    """
    gRPC service implementation for inter-node communication.
    """

    def __init__(self, distributed_node: DistributedNode):
        """
        Initialize gRPC servicer.

        Args:
            distributed_node: Reference to the distributed node manager
        """
        self.node = distributed_node
        logger.info(f"gRPC servicer initialized for node {distributed_node.node_id}")

    async def Ping(
        self,
        request: node_pb2.PingRequest,
        context: grpc.aio.ServicerContext
    ) -> node_pb2.PingResponse:
        """
        Handle ping/heartbeat RPC.

        Args:
            request: Ping request with sender_id and timestamp
            context: gRPC context

        Returns:
            Ping response with node status
        """
        try:
            sender_id = request.sender_id
            timestamp = request.timestamp

            logger.debug(f"Node {self.node.node_id}: Received gRPC ping from node {sender_id}")

            # Update Lamport clock
            self.node.clock.receive_event(timestamp)

            return node_pb2.PingResponse(
                responder_id=self.node.node_id,
                timestamp=self.node.clock.time(),
                status="ok"
            )

        except Exception as e:
            logger.error(f"Error handling ping: {e}")
            await context.abort(grpc.StatusCode.INTERNAL, str(e))

    async def SendElection(
        self,
        request: node_pb2.ElectionRequest,
        context: grpc.aio.ServicerContext
    ) -> node_pb2.ElectionResponse:
        """
        Handle election message RPC (Bully algorithm).

        Args:
            request: Election request with sender_id, message_type, timestamp
            context: gRPC context

        Returns:
            Election response acknowledging the message
        """
        try:
            sender_id = request.sender_id
            message_type = request.message_type
            timestamp = request.timestamp

            logger.debug(
                f"Node {self.node.node_id}: Received gRPC {message_type} from node {sender_id}"
            )

            # Create ElectionMessage and delegate to node manager
            from .election import ElectionMessage
            msg = ElectionMessage(
                sender_id=sender_id,
                message_type=message_type,
                timestamp=timestamp
            )
            await self.node.handle_election_message(msg)

            return node_pb2.ElectionResponse(
                acknowledged=True,
                timestamp=self.node.clock.time()
            )

        except Exception as e:
            logger.error(f"Error handling election message: {e}")
            await context.abort(grpc.StatusCode.INTERNAL, str(e))

    async def AssignTask(
        self,
        request: node_pb2.TaskAssignment,
        context: grpc.aio.ServicerContext
    ) -> node_pb2.TaskAcknowledgement:
        """
        Handle task assignment RPC.

        Args:
            request: Task assignment with task_id, task_type, payload, etc.
            context: gRPC context

        Returns:
            Task acknowledgement
        """
        try:
            task_id = request.task_id
            task_type = request.task_type
            payload = request.payload  # bytes
            timestamp = request.timestamp
            assigned_by = request.assigned_by

            logger.info(
                f"Node {self.node.node_id}: Received gRPC task {task_id} from node {assigned_by}"
            )

            # Update Lamport clock
            self.node.clock.receive_event(timestamp)

            # Process task based on type
            if task_type == "analyze_image" and self.node.on_task_assigned:
                # Schedule task processing
                asyncio.create_task(self.node.on_task_assigned(task_id, payload))

                return node_pb2.TaskAcknowledgement(
                    task_id=task_id,
                    accepted=True,
                    message="Task accepted for processing"
                )
            else:
                return node_pb2.TaskAcknowledgement(
                    task_id=task_id,
                    accepted=False,
                    message=f"Unknown task type: {task_type}"
                )

        except Exception as e:
            logger.error(f"Error handling task assignment: {e}")
            await context.abort(grpc.StatusCode.INTERNAL, str(e))

    async def GetStatus(
        self,
        request: node_pb2.StatusRequest,
        context: grpc.aio.ServicerContext
    ) -> node_pb2.StatusResponse:
        """
        Handle status query RPC.

        Args:
            request: Status request with sender_id
            context: gRPC context

        Returns:
            Status response with comprehensive node information
        """
        try:
            sender_id = request.sender_id
            logger.debug(f"Node {self.node.node_id}: Received gRPC status query from node {sender_id}")

            status = self.node.get_status()

            return node_pb2.StatusResponse(
                node_id=self.node.node_id,
                is_leader=self.node.is_leader,
                leader_id=self.node.leader_id or -1,
                lamport_clock=self.node.clock.time(),
                active_nodes=status.get("alive_nodes", []),
                pending_tasks=len(self.node._task_queue),
                hardware_info=f"Node {self.node.node_id}"
            )

        except Exception as e:
            logger.error(f"Error handling status query: {e}")
            await context.abort(grpc.StatusCode.INTERNAL, str(e))


async def serve_grpc(distributed_node: DistributedNode, port: int = 50051) -> grpc.aio.Server:
    """
    Start gRPC server for inter-node communication.

    Args:
        distributed_node: The distributed node manager instance
        port: gRPC port to listen on (default: 50051)

    Returns:
        Running gRPC server
    """
    server = grpc.aio.server()
    node_pb2_grpc.add_NodeServiceServicer_to_server(
        NodeServiceServicer(distributed_node),
        server
    )

    listen_addr = f"0.0.0.0:{port}"
    server.add_insecure_port(listen_addr)

    logger.info(f"Starting gRPC server for node {distributed_node.node_id} on {listen_addr}")
    await server.start()
    logger.info(f"gRPC server running on {listen_addr}")

    return server
