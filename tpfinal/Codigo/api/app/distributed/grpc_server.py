"""
Implementação do servidor gRPC para comunicação entre nós distribuídos.

Implementa o NodeService definido em node.proto.
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
    """Implementação do serviço gRPC para comunicação entre nós."""

    def __init__(self, distributed_node: DistributedNode):
        """
        Inicializa o servicer gRPC.

        Args:
            distributed_node: Referência ao gerenciador de nó distribuído
        """
        self.node = distributed_node
        logger.info(f"gRPC servicer initialized for node {distributed_node.node_id}")

    async def Ping(
        self,
        request: node_pb2.PingRequest,
        context: grpc.aio.ServicerContext
    ) -> node_pb2.PingResponse:
        """Processa RPC de ping/heartbeat."""
        try:
            sender_id = request.sender_id
            timestamp = request.timestamp

            logger.debug(f"Node {self.node.node_id}: Received gRPC ping from node {sender_id}")

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
        """Processa RPC de mensagem de eleição (algoritmo Bully)."""
        try:
            sender_id = request.sender_id
            message_type = request.message_type
            timestamp = request.timestamp

            logger.debug(
                f"Node {self.node.node_id}: Received gRPC {message_type} from node {sender_id}"
            )

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
        """Processa RPC de atribuição de tarefa."""
        try:
            task_id = request.task_id
            task_type = request.task_type
            payload = request.payload
            timestamp = request.timestamp
            assigned_by = request.assigned_by

            logger.info(
                f"Node {self.node.node_id}: Received gRPC task {task_id} from node {assigned_by}"
            )

            self.node.clock.receive_event(timestamp)

            if task_type == "analyze_image" and self.node.on_task_assigned:
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
        """Processa RPC de consulta de status."""
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
    Inicia o servidor gRPC para comunicação entre nós.

    Args:
        distributed_node: Instância do gerenciador de nó distribuído
        port: Porta gRPC para escutar (padrão: 50051)

    Retorna:
        Servidor gRPC em execução
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
