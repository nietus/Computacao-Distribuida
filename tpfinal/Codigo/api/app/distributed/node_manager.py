"""
Gerenciador de Nó Distribuído.

Orquestra todos os componentes do sistema distribuído:
- Relógios lógicos de Lamport
- Algoritmo de eleição Bully
- Comunicação RPC
- Detecção de falhas baseada em heartbeat
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable

from .election import BullyElection, ElectionMessage
from .heartbeat import HeartbeatMonitor
from .lamport_clock import LamportClock
from .rpc_client import GRPCClient
from .task_distributor import TaskDistributor

logger = logging.getLogger(__name__)


class DistributedNode:
    """
    Gerenciador principal do nó distribuído.

    Integra todos os algoritmos de sistemas distribuídos e fornece
    interface de alto nível para a camada de aplicação.
    """

    def __init__(
        self,
        node_id: int,
        node_addresses: dict[int, str],
        on_task_assigned: Callable[[str, bytes], asyncio.Future] | None = None,
    ):
        """
        Inicializa o nó distribuído.

        Args:
            node_id: Identificador único deste nó (1, 2, 3)
            node_addresses: Mapeamento de node_id -> "host:grpc_port" (ex: "node1:50051")
            on_task_assigned: Callback quando tarefa é atribuída a este nó
        """
        self.node_id = node_id
        self.node_addresses = node_addresses
        self.all_node_ids = list(node_addresses.keys())
        self.on_task_assigned = on_task_assigned
        self.on_task_assigned_tensorflow = None
        self.grpc_server = None

        self.clock = LamportClock()

        logger.info(f"Node {node_id}: Using gRPC for inter-node communication")
        self.rpc_client = GRPCClient(node_id, node_addresses)

        self.election = BullyElection(
            node_id=node_id,
            all_node_ids=self.all_node_ids,
            send_message_callback=self._send_election_message,
            on_leader_change=self._on_leader_change
        )

        self.heartbeat = HeartbeatMonitor(
            node_id=node_id,
            all_node_ids=self.all_node_ids,
            ping_callback=self._ping_node,
            on_node_failed=self._on_node_failed,
            on_node_recovered=self._on_node_recovered,
            on_leader_failed=self._on_leader_failed
        )

        self.task_distributor = TaskDistributor(
            node_id=node_id,
            is_leader_callback=lambda: self.is_leader,
            get_alive_nodes_callback=lambda: self.heartbeat.get_alive_nodes(),
            assign_task_rpc=self._assign_task_via_rpc
        )

        self.running = False
        self.tasks_processed = 0
        self.tasks_queue: asyncio.Queue = asyncio.Queue()

        logger.info(
            f"Node {node_id}: Initialized distributed node with addresses {node_addresses}"
        )

    @property
    def is_leader(self) -> bool:
        """Verifica se este nó é o líder atual."""
        return self.election.is_leader

    @property
    def leader_id(self) -> int | None:
        """Retorna o ID do líder atual."""
        return self.election.leader_id

    async def start(self) -> None:
        """Inicia o nó distribuído."""
        if self.running:
            logger.warning(f"Node {self.node_id}: Already running")
            return

        self.running = True
        logger.info(f"Node {self.node_id}: Starting distributed node...")

        from .grpc_server import serve_grpc
        grpc_port = int(os.getenv("GRPC_PORT", "50051"))
        self.grpc_server = await serve_grpc(self, port=grpc_port)
        logger.info(f"Node {self.node_id}: gRPC server started on port {grpc_port}")

        await self.heartbeat.start()

        await asyncio.sleep(1.0)

        logger.info(f"Node {self.node_id}: Starting initial leader election...")
        await self.election.start_election()

        asyncio.create_task(self._process_tasks())

        logger.info(
            f"Node {self.node_id}: Started successfully. "
            f"Leader: {self.leader_id}, Clock: {self.clock.time()}"
        )

    async def stop(self) -> None:
        """Para o nó distribuído."""
        logger.info(f"Node {self.node_id}: Stopping...")
        self.running = False
        await self.heartbeat.stop()
        await self.rpc_client.close()

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
        Submete tarefa de análise de imagem ao sistema distribuído (PyTorch).

        Líder distribui para o nó menos carregado.
        Seguidor processa localmente.

        Args:
            task_id: Identificador único da tarefa
            image_bytes: Dados da imagem

        Retorna:
            Dict com informações da atribuição
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
        Submete tarefa de análise de imagem ao sistema distribuído (TensorFlow).

        Líder distribui para o nó menos carregado.
        Seguidor processa localmente.

        Args:
            task_id: Identificador único da tarefa
            image_bytes: Dados da imagem

        Retorna:
            Dict com informações da atribuição
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
        """Atribui tarefa a outro nó via RPC."""
        timestamp = self.clock.send_event()
        return await self.rpc_client.assign_task(
            target_node_id,
            task_id,
            task_type,
            payload,
            timestamp
        )

    def get_status(self) -> dict[str, Any]:
        """Retorna o status atual do nó."""
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

    async def handle_election_message(self, msg: ElectionMessage) -> None:
        """Processa mensagem de eleição recebida."""
        self.clock.receive_event(msg.timestamp)
        await self.election.handle_message(msg)

    async def handle_task_assignment(
        self,
        task_id: str,
        task_type: str,
        payload: bytes
    ) -> dict[str, Any]:
        """
        Processa atribuição de tarefa do líder.

        Args:
            task_id: Identificador único da tarefa
            task_type: Tipo da tarefa
            payload: Dados da tarefa

        Retorna:
            Dict de confirmação
        """
        logger.info(f"Node {self.node_id}: Received task assignment {task_id}")

        try:
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

    async def _send_election_message(
        self,
        target_node_id: int,
        msg: ElectionMessage
    ) -> None:
        """Envia mensagem de eleição via RPC."""
        msg.timestamp = self.clock.send_event()
        await self.rpc_client.send_election_message(
            target_node_id,
            msg.message_type,
            msg.timestamp
        )

    async def _ping_node(self, target_node_id: int) -> bool:
        """Envia ping para outro nó (usado pelo monitor de heartbeat)."""
        timestamp = self.clock.send_event()
        response = await self.rpc_client.ping(target_node_id, timestamp)

        if response:
            self.clock.receive_event(response.get("timestamp", timestamp))
            return True
        return False

    def _on_leader_change(self, new_leader_id: int) -> None:
        """Callback quando o líder muda."""
        logger.info(f"Node {self.node_id}: Leader changed to {new_leader_id}")
        self.heartbeat.set_leader(new_leader_id)

    def _on_node_failed(self, failed_node_id: int) -> None:
        """Callback quando um nó falha."""
        logger.warning(f"Node {self.node_id}: Node {failed_node_id} declared failed")

    def _on_node_recovered(self, recovered_node_id: int) -> None:
        """Callback quando um nó falho se recupera."""
        logger.info(f"Node {self.node_id}: Node {recovered_node_id} recovered")

    async def _on_leader_failed(self) -> None:
        """Callback quando o líder falha - inicia nova eleição."""
        logger.critical(f"Node {self.node_id}: Leader failed! Starting new election...")
        self.election.current_leader = None
        await self.election.start_election()

    async def _process_tasks(self) -> None:
        """Loop de processamento de tarefas em background."""
        logger.info(f"Node {self.node_id}: Task processing loop started")

        while self.running:
            try:
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


def create_node_from_env() -> DistributedNode:
    """
    Cria DistributedNode a partir de variáveis de ambiente.

    Variáveis esperadas:
    - NODE_ID: ID deste nó (1, 2 ou 3)
    - NODE_1_ADDRESS: Endereço do nó 1 (ex: "node1:50051")
    - NODE_2_ADDRESS: Endereço do nó 2
    - NODE_3_ADDRESS: Endereço do nó 3
    - GRPC_PORT: Porta gRPC para escutar (padrão: 50051)

    Nota: gRPC é o método exclusivo de comunicação entre nós.
    """
    node_id = int(os.getenv("NODE_ID", "1"))

    node_addresses = {
        1: os.getenv("NODE_1_ADDRESS", "node1:50051"),
        2: os.getenv("NODE_2_ADDRESS", "node2:50051"),
        3: os.getenv("NODE_3_ADDRESS", "node3:50051"),
    }

    logger.info(
        f"Creating node {node_id} with gRPC addresses: {node_addresses}"
    )

    return DistributedNode(node_id=node_id, node_addresses=node_addresses)
