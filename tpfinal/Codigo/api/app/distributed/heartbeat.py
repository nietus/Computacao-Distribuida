"""
Tolerância a Falhas com Monitoramento de Heartbeat.

Implementa detecção de falhas usando heartbeats periódicos entre nós.
Dispara eleição de líder quando falha do líder é detectada.
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
    """Informações de saúde de um nó."""
    node_id: int
    last_heartbeat: float
    is_alive: bool = True
    consecutive_failures: int = 0


class HeartbeatMonitor:
    """
    Detecção de falhas baseada em heartbeat.

    Propriedades:
    - Ping periódico para todos os nós
    - Rastreia último heartbeat bem-sucedido
    - Declara nó como falho após N timeouts consecutivos
    - Dispara callbacks em falha/recuperação de nó
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
        Inicializa o monitor de heartbeat.

        Args:
            node_id: ID deste nó
            all_node_ids: Todos os nós no cluster
            ping_callback: Função assíncrona para ping em outro nó, retorna bool de sucesso
            on_node_failed: Callback quando nó é declarado falho
            on_node_recovered: Callback quando nó falho se recupera
            on_leader_failed: Callback quando líder falha (dispara eleição)
        """
        self.node_id = node_id
        self.all_node_ids = [nid for nid in all_node_ids if nid != node_id]
        self.ping_callback = ping_callback
        self.on_node_failed = on_node_failed
        self.on_node_recovered = on_node_recovered
        self.on_leader_failed = on_leader_failed

        self.node_health: dict[int, NodeHealth] = {
            nid: NodeHealth(node_id=nid, last_heartbeat=time.time())
            for nid in self.all_node_ids
        }

        self.heartbeat_interval = 2.0
        self.failure_threshold = 3
        self.timeout = 1.5

        self.current_leader_id: int | None = None
        self.running = False
        self._monitor_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

        logger.info(
            f"Node {node_id}: Heartbeat monitor initialized, "
            f"monitoring {len(self.all_node_ids)} nodes"
        )

    def set_leader(self, leader_id: int) -> None:
        """Atualiza o ID do líder atual."""
        self.current_leader_id = leader_id
        logger.info(f"Node {self.node_id}: Leader set to {leader_id}")

    async def start(self) -> None:
        """Inicia o monitoramento de heartbeat."""
        if self.running:
            logger.warning(f"Node {self.node_id}: Heartbeat monitor already running")
            return

        self.running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Node {self.node_id}: Heartbeat monitor started")

    async def stop(self) -> None:
        """Para o monitoramento de heartbeat."""
        self.running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info(f"Node {self.node_id}: Heartbeat monitor stopped")

    async def _monitor_loop(self) -> None:
        """Loop principal de monitoramento."""
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
        """Envia heartbeat para todos os nós e verifica respostas."""
        tasks = [self._ping_node(nid) for nid in self.all_node_ids]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _ping_node(self, target_node_id: int) -> None:
        """
        Envia ping para um nó específico e atualiza status de saúde.

        Args:
            target_node_id: Nó para enviar ping
        """
        try:
            success = await asyncio.wait_for(
                self.ping_callback(target_node_id),
                timeout=self.timeout
            )

            async with self._lock:
                health = self.node_health[target_node_id]

                if success:
                    health.last_heartbeat = time.time()
                    health.consecutive_failures = 0

                    if not health.is_alive:
                        logger.info(f"Node {self.node_id}: Node {target_node_id} RECOVERED")
                        health.is_alive = True
                        if self.on_node_recovered:
                            self.on_node_recovered(target_node_id)
                else:
                    health.consecutive_failures += 1
                    logger.warning(
                        f"Node {self.node_id}: Ping to {target_node_id} failed "
                        f"({health.consecutive_failures}/{self.failure_threshold})"
                    )

                    if (
                        health.consecutive_failures >= self.failure_threshold
                        and health.is_alive
                    ):
                        logger.error(f"Node {self.node_id}: Node {target_node_id} DECLARED FAILED")
                        health.is_alive = False

                        if self.on_node_failed:
                            self.on_node_failed(target_node_id)

                        if target_node_id == self.current_leader_id:
                            logger.critical(
                                f"Node {self.node_id}: LEADER {target_node_id} FAILED! "
                                "Triggering election..."
                            )
                            if self.on_leader_failed:
                                asyncio.create_task(self.on_leader_failed())

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
        """Retorna lista de nós atualmente vivos (incluindo este)."""
        alive = [self.node_id]
        for nid, health in self.node_health.items():
            if health.is_alive:
                alive.append(nid)
        return sorted(alive)

    def is_node_alive(self, node_id: int) -> bool:
        """Verifica se um nó específico está vivo."""
        if node_id == self.node_id:
            return True
        health = self.node_health.get(node_id)
        return health.is_alive if health else False

    def get_health_summary(self) -> dict[int, dict]:
        """Retorna resumo do status de saúde de todos os nós."""
        summary = {}
        for nid, health in self.node_health.items():
            summary[nid] = {
                "is_alive": health.is_alive,
                "last_heartbeat": health.last_heartbeat,
                "time_since_heartbeat": time.time() - health.last_heartbeat,
                "consecutive_failures": health.consecutive_failures
            }
        return summary
