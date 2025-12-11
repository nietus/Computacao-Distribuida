"""
Cliente RPC baseado em gRPC para comunicação entre nós.

Implementação de produção usando gRPC ao invés de HTTP/JSON.
Proporciona melhor desempenho com protocol buffers binários.
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
    Cliente RPC de produção usando gRPC com Protocol Buffers.

    Proporciona comunicação binária eficiente entre nós distribuídos.
    """

    def __init__(self, node_id: int, node_addresses: dict[int, str]):
        """
        Inicializa o cliente gRPC.

        Args:
            node_id: ID deste nó
            node_addresses: Mapeamento de node_id -> "host:port" (portas gRPC)
        """
        self.node_id = node_id
        self.node_addresses = node_addresses
        self._channels: dict[int, grpc.aio.Channel] = {}
        self._stubs: dict[int, node_pb2_grpc.NodeServiceStub] = {}

        logger.info(f"gRPC Client initialized for node {node_id}")
        logger.info(f"Known nodes: {node_addresses}")

    async def _get_stub(self, target_node_id: int) -> node_pb2_grpc.NodeServiceStub | None:
        """Obtém ou cria stub gRPC para o nó alvo."""
        if target_node_id not in self._stubs:
            address = self.node_addresses.get(target_node_id)
            if not address:
                logger.warning(f"No address for node {target_node_id}")
                return None

            channel = grpc.aio.insecure_channel(address)
            self._channels[target_node_id] = channel
            self._stubs[target_node_id] = node_pb2_grpc.NodeServiceStub(channel)
            logger.debug(f"Created gRPC channel to node {target_node_id} at {address}")

        return self._stubs[target_node_id]

    def get_node_address(self, target_node_id: int) -> str | None:
        """Retorna o endereço do nó alvo."""
        return self.node_addresses.get(target_node_id)

    async def _invalidate_channel(self, target_node_id: int) -> None:
        """
        Invalida canal em cache para um nó.

        Chamado em falhas de conexão para que o próximo ping crie uma conexão nova.
        Permite recuperação quando um nó reinicia.
        """
        if target_node_id in self._channels:
            try:
                await self._channels[target_node_id].close()
            except Exception:
                pass
            del self._channels[target_node_id]
        if target_node_id in self._stubs:
            del self._stubs[target_node_id]
        logger.debug(f"Node {self.node_id}: Invalidated channel to node {target_node_id}")

    async def ping(self, target_node_id: int, timestamp: int) -> dict[str, Any] | None:
        """
        Envia ping/heartbeat para o nó alvo via gRPC.

        Args:
            target_node_id: Nó para enviar ping
            timestamp: Timestamp de Lamport

        Retorna:
            Dict de resposta ou None se falhou
        """
        try:
            stub = await self._get_stub(target_node_id)
            if not stub:
                return None

            logger.debug(f"Node {self.node_id}: Pinging node {target_node_id} via gRPC")

            request = node_pb2.PingRequest(
                sender_id=self.node_id,
                timestamp=timestamp
            )

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
            await self._invalidate_channel(target_node_id)
            return None
        except grpc.RpcError as e:
            logger.debug(f"Node {self.node_id}: gRPC error pinging {target_node_id}: {e.code()}")
            await self._invalidate_channel(target_node_id)
            return None
        except Exception as e:
            logger.debug(f"Node {self.node_id}: Failed to ping {target_node_id}: {e}")
            await self._invalidate_channel(target_node_id)
            return None

    async def send_election_message(
        self,
        target_node_id: int,
        message_type: str,
        timestamp: int
    ) -> bool:
        """
        Envia mensagem de eleição via gRPC (algoritmo Bully).

        Args:
            target_node_id: Nó de destino
            message_type: "ELECTION", "OK" ou "COORDINATOR"
            timestamp: Timestamp de Lamport

        Retorna:
            True se bem-sucedido
        """
        try:
            stub = await self._get_stub(target_node_id)
            if not stub:
                return False

            logger.debug(
                f"Node {self.node_id}: Sending {message_type} to {target_node_id} via gRPC"
            )

            request = node_pb2.ElectionRequest(
                sender_id=self.node_id,
                message_type=message_type,
                timestamp=timestamp
            )

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
        Atribui tarefa a outro nó via gRPC.

        Args:
            target_node_id: Nó para atribuir a tarefa
            task_id: Identificador único da tarefa
            task_type: Tipo da tarefa (ex: "analyze_image")
            payload: Dados da tarefa (binário)
            timestamp: Timestamp de Lamport

        Retorna:
            Dict de confirmação ou None se falhou
        """
        try:
            stub = await self._get_stub(target_node_id)
            if not stub:
                return None

            logger.info(
                f"Node {self.node_id}: Assigning task {task_id} to node {target_node_id} via gRPC"
            )

            request = node_pb2.TaskAssignment(
                task_id=task_id,
                task_type=task_type,
                payload=payload,
                timestamp=timestamp,
                assigned_by=self.node_id
            )

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
        Consulta status de outro nó via gRPC.

        Args:
            target_node_id: Nó para consultar

        Retorna:
            Dict de status ou None se falhou
        """
        try:
            stub = await self._get_stub(target_node_id)
            if not stub:
                return None

            logger.debug(f"Node {self.node_id}: Querying status of node {target_node_id} via gRPC")

            request = node_pb2.StatusRequest(sender_id=self.node_id)

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
        """Fecha todos os canais gRPC."""
        logger.info(f"Node {self.node_id}: Closing gRPC connections")
        for node_id, channel in self._channels.items():
            await channel.close()
            logger.debug(f"Closed gRPC channel to node {node_id}")

        self._channels.clear()
        self._stubs.clear()
