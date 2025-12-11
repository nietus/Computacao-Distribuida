"""
Sistema de Distribuição de Tarefas para Análise de Imagens com ML.

Distribui tarefas de análise de imagem entre os nós do cluster usando:
- Atribuição de tarefas baseada em líder
- Balanceamento de carga (nó menos carregado)
- Ordenação por relógio de Lamport
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class NodeLoad:
    """Rastreia a carga de cada nó."""
    node_id: int
    pending_tasks: int = 0
    is_alive: bool = True


class TaskDistributor:
    """
    Sistema de atribuição de tarefas distribuído.

    O nó líder recebe tarefas e as distribui para os nós disponíveis.
    Usa algoritmo de menor carga para balanceamento.
    """

    def __init__(
        self,
        node_id: int,
        is_leader_callback: Callable[[], bool],
        get_alive_nodes_callback: Callable[[], list[int]],
        assign_task_rpc: Callable[[int, str, str, bytes], asyncio.Future],
    ):
        """
        Inicializa o distribuidor de tarefas.

        Args:
            node_id: ID deste nó
            is_leader_callback: Função que retorna True se este nó é líder
            get_alive_nodes_callback: Função que retorna lista de IDs dos nós ativos
            assign_task_rpc: Função RPC para atribuir tarefa a outro nó
        """
        self.node_id = node_id
        self.is_leader = is_leader_callback
        self.get_alive_nodes = get_alive_nodes_callback
        self.assign_task_rpc = assign_task_rpc

        self.node_loads: dict[int, NodeLoad] = {}
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
        Submete tarefa para processamento.

        Se este é o líder:
        - Distribui para o nó menos carregado
        Se este é um seguidor:
        - Processa localmente

        Args:
            task_id: Identificador único da tarefa
            task_type: Tipo da tarefa (ex: "analyze_image")
            payload: Dados da tarefa (bytes da imagem)

        Retorna:
            Dict com informações da atribuição
        """
        if self.is_leader():
            target_node = self._select_node_for_task()
            logger.info(
                f"Node {self.node_id} (LEADER): Assigning task {task_id} to node {target_node}"
            )

            if target_node == self.node_id:
                await self.local_queue.put((task_id, task_type, payload))
                self._update_load(self.node_id, increment=1)
                return {
                    "assigned_to": self.node_id,
                    "status": "queued_local"
                }
            else:
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
        Seleciona o melhor nó para a tarefa usando algoritmo de menor carga.

        Retorna:
            ID do nó para atribuir a tarefa
        """
        alive_nodes = self.get_alive_nodes()

        if not alive_nodes:
            logger.warning(f"Node {self.node_id}: No alive nodes, using self")
            return self.node_id

        for node_id in alive_nodes:
            if node_id not in self.node_loads:
                self.node_loads[node_id] = NodeLoad(node_id=node_id)

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
        """Atualiza o rastreamento de carga de um nó."""
        if node_id not in self.node_loads:
            self.node_loads[node_id] = NodeLoad(node_id=node_id)

        self.node_loads[node_id].pending_tasks += increment

        if self.node_loads[node_id].pending_tasks < 0:
            self.node_loads[node_id].pending_tasks = 0

    async def get_next_task(self) -> tuple[str, str, bytes] | None:
        """
        Obtém a próxima tarefa da fila local.

        Retorna:
            Tupla (task_id, task_type, payload) ou None se a fila estiver vazia
        """
        try:
            task = await asyncio.wait_for(self.local_queue.get(), timeout=0.1)
            return task
        except asyncio.TimeoutError:
            return None

    def task_completed(self, node_id: int) -> None:
        """Marca tarefa como concluída em um nó."""
        self._update_load(node_id, increment=-1)
        logger.debug(
            f"Node {self.node_id}: Task completed on node {node_id}, "
            f"remaining: {self.node_loads.get(node_id, NodeLoad(node_id)).pending_tasks}"
        )

    def get_load_summary(self) -> dict[int, int]:
        """Retorna resumo da carga de todos os nós."""
        return {
            node_id: load.pending_tasks
            for node_id, load in self.node_loads.items()
        }
