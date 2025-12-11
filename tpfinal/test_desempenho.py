#!/usr/bin/env python3
"""
Script de Teste de Desempenho para o Sistema Distribuído Skin IA.

Este script testa:
1. Latência de requisições HTTP
2. Throughput do sistema com múltiplas requisições simultâneas
3. Distribuição de tarefas entre nós
4. Tempo de detecção de falha e reeleição de líder
5. Funcionamento do relógio de Lamport
6. Balanceamento de carga

Uso:
    python test_desempenho.py [--host HOST] [--port PORT] [--nodes NODES]

Exemplos:
    python test_desempenho.py                          # Testes básicos
    python test_desempenho.py --test-all               # Todos os testes
    python test_desempenho.py --test-load --requests 50 # Teste de carga
"""

import argparse
import asyncio
import aiohttp
import time
import statistics
import json
import random
import sys
from dataclasses import dataclass
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import requests
from pathlib import Path


@dataclass
class TestResult:
    """Resultado de um teste."""
    name: str
    passed: bool
    duration_ms: float
    message: str
    details: Optional[dict] = None


class DistributedSystemTester:
    """Classe para testar o sistema distribuído Skin IA."""

    def __init__(self, base_url: str = "http://localhost"):
        self.base_url = base_url
        self.node_ports = [8001, 8002, 8003]
        self.results: list[TestResult] = []

        # Imagem de teste (pequeno PNG fake para testes)
        self.test_image = self._create_test_image()

    def _create_test_image(self) -> bytes:
        """Carrega uma imagem real do diretório img para testes."""
        # Usar imagem real do projeto
        img_path = Path(__file__).parent / "img" / "bcp8.jpg"

        if img_path.exists():
            with open(img_path, "rb") as f:
                return f.read()

        # Fallback: tentar caminho alternativo
        alt_path = Path("img/bcp8.jpg")
        if alt_path.exists():
            with open(alt_path, "rb") as f:
                return f.read()

        # Último fallback: criar imagem com PIL
        try:
            from PIL import Image
            import io
            img = Image.new('RGB', (192, 192), color=(128, 64, 64))
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            return buffer.getvalue()
        except ImportError:
            raise FileNotFoundError("Não foi possível encontrar imagem de teste em img/bcp8.jpg")

    def _record_result(self, name: str, passed: bool, duration_ms: float,
                       message: str, details: dict = None):
        """Registra resultado de um teste."""
        result = TestResult(
            name=name,
            passed=passed,
            duration_ms=duration_ms,
            message=message,
            details=details
        )
        self.results.append(result)

        status = "PASSOU" if passed else "FALHOU"
        print(f"  [{status}] {name}: {message} ({duration_ms:.2f}ms)")
        if details:
            for key, value in details.items():
                print(f"         {key}: {value}")

    # =========================================================================
    # TESTES DE CONECTIVIDADE
    # =========================================================================

    def test_healthcheck(self) -> bool:
        """Testa endpoint de healthcheck em cada nó."""
        print("\n=== Teste de Healthcheck ===")
        all_passed = True

        for port in self.node_ports:
            url = f"http://localhost:{port}/healthz"
            start = time.time()

            try:
                response = requests.get(url, timeout=5)
                duration = (time.time() - start) * 1000

                if response.status_code == 200:
                    self._record_result(
                        f"Healthcheck Node {port}",
                        True,
                        duration,
                        f"Status: OK"
                    )
                else:
                    self._record_result(
                        f"Healthcheck Node {port}",
                        False,
                        duration,
                        f"Status code: {response.status_code}"
                    )
                    all_passed = False
            except Exception as e:
                duration = (time.time() - start) * 1000
                self._record_result(
                    f"Healthcheck Node {port}",
                    False,
                    duration,
                    f"Erro: {str(e)}"
                )
                all_passed = False

        return all_passed

    # =========================================================================
    # TESTES DO SISTEMA DISTRIBUÍDO
    # =========================================================================

    def test_distributed_status(self) -> bool:
        """Testa status do sistema distribuído em cada nó."""
        print("\n=== Teste de Status Distribuído ===")
        all_passed = True

        for port in self.node_ports:
            url = f"http://localhost:{port}/v1/distributed/status"
            start = time.time()

            try:
                response = requests.get(url, timeout=5)
                duration = (time.time() - start) * 1000

                if response.status_code == 200:
                    data = response.json()
                    self._record_result(
                        f"Distributed Status Node {port}",
                        True,
                        duration,
                        f"Node ID: {data.get('node_id')}, Leader: {data.get('leader_id')}",
                        {
                            "is_leader": data.get("is_leader"),
                            "lamport_clock": data.get("lamport_clock"),
                            "election_state": data.get("election_state"),
                            "alive_nodes": data.get("alive_nodes")
                        }
                    )
                elif response.status_code == 503:
                    self._record_result(
                        f"Distributed Status Node {port}",
                        False,
                        duration,
                        "Sistema distribuído não habilitado"
                    )
                    all_passed = False
                else:
                    self._record_result(
                        f"Distributed Status Node {port}",
                        False,
                        duration,
                        f"Status code: {response.status_code}"
                    )
                    all_passed = False
            except Exception as e:
                duration = (time.time() - start) * 1000
                self._record_result(
                    f"Distributed Status Node {port}",
                    False,
                    duration,
                    f"Erro: {str(e)}"
                )
                all_passed = False

        return all_passed

    def test_leader_consistency(self) -> bool:
        """Verifica se todos os nós concordam sobre quem é o líder."""
        print("\n=== Teste de Consistência de Líder ===")

        leaders = []
        start = time.time()

        for port in self.node_ports:
            url = f"http://localhost:{port}/v1/distributed/leader"
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    leaders.append(data.get("leader_id"))
            except:
                leaders.append(None)

        duration = (time.time() - start) * 1000

        # Verifica se todos concordam
        valid_leaders = [l for l in leaders if l is not None]

        if len(valid_leaders) == 0:
            self._record_result(
                "Consistência de Líder",
                False,
                duration,
                "Nenhum nó respondeu"
            )
            return False

        if len(set(valid_leaders)) == 1:
            self._record_result(
                "Consistência de Líder",
                True,
                duration,
                f"Todos os nós concordam: Líder = Node {valid_leaders[0]}",
                {"leaders_reported": leaders}
            )
            return True
        else:
            self._record_result(
                "Consistência de Líder",
                False,
                duration,
                f"Inconsistência detectada!",
                {"leaders_reported": leaders}
            )
            return False

    def test_lamport_clock_ordering(self) -> bool:
        """Testa se o relógio de Lamport está incrementando corretamente."""
        print("\n=== Teste de Relógio de Lamport ===")

        clocks = []
        start = time.time()

        # Faz múltiplas requisições e verifica se o clock aumenta
        port = 8001  # Usa primeiro nó
        url = f"http://localhost:{port}/v1/distributed/status"

        for i in range(5):
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    clocks.append(data.get("lamport_clock", 0))
                time.sleep(0.1)
            except:
                pass

        duration = (time.time() - start) * 1000

        if len(clocks) < 2:
            self._record_result(
                "Relógio de Lamport",
                False,
                duration,
                "Não foi possível obter valores do relógio"
            )
            return False

        # Verifica se o clock está aumentando (monotônico)
        is_monotonic = all(clocks[i] <= clocks[i+1] for i in range(len(clocks)-1))

        self._record_result(
            "Relógio de Lamport",
            is_monotonic,
            duration,
            f"Valores: {clocks} - {'Monotônico' if is_monotonic else 'NÃO monotônico'}",
            {"clock_values": clocks, "is_monotonic": is_monotonic}
        )

        return is_monotonic

    # =========================================================================
    # TESTES DE SUBMISSÃO DE TAREFAS
    # =========================================================================

    def test_task_submission(self) -> bool:
        """Testa submissão de tarefas de análise de imagem."""
        print("\n=== Teste de Submissão de Tarefas ===")

        url = f"{self.base_url}/v1/analyze-pytorch"
        start = time.time()

        try:
            files = {"file": ("test.png", self.test_image, "image/png")}
            response = requests.post(url, files=files, timeout=30)
            duration = (time.time() - start) * 1000

            if response.status_code == 202:
                data = response.json()
                self._record_result(
                    "Submissão de Tarefa",
                    True,
                    duration,
                    f"Request ID: {data.get('request_id')}",
                    {
                        "status": data.get("status"),
                        "framework": data.get("framework"),
                        "distributed": data.get("distributed"),
                        "assigned_to_node": data.get("assigned_to_node")
                    }
                )
                return True
            else:
                self._record_result(
                    "Submissão de Tarefa",
                    False,
                    duration,
                    f"Status code: {response.status_code}"
                )
                return False
        except Exception as e:
            duration = (time.time() - start) * 1000
            self._record_result(
                "Submissão de Tarefa",
                False,
                duration,
                f"Erro: {str(e)}"
            )
            return False

    # =========================================================================
    # TESTES DE DESEMPENHO
    # =========================================================================

    async def test_concurrent_load(self, num_requests: int = 10) -> bool:
        """Teste de carga com requisições concorrentes."""
        print(f"\n=== Teste de Carga ({num_requests} requisições) ===")

        latencies = []
        successes = 0
        failures = 0
        node_assignments = {1: 0, 2: 0, 3: 0}

        start_total = time.time()

        async with aiohttp.ClientSession() as session:
            tasks = []

            for i in range(num_requests):
                task = self._submit_request_async(session, i)
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    failures += 1
                elif result:
                    successes += 1
                    latencies.append(result.get("latency_ms", 0))
                    node = result.get("assigned_to_node")
                    if node in node_assignments:
                        node_assignments[node] += 1
                else:
                    failures += 1

        total_duration = (time.time() - start_total) * 1000

        # Calcula estatísticas
        if latencies:
            avg_latency = statistics.mean(latencies)
            min_latency = min(latencies)
            max_latency = max(latencies)
            p95_latency = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max_latency
        else:
            avg_latency = min_latency = max_latency = p95_latency = 0

        throughput = (successes / total_duration) * 1000 if total_duration > 0 else 0

        passed = successes > 0 and failures < num_requests * 0.5  # Até 50% falha ok

        self._record_result(
            "Teste de Carga",
            passed,
            total_duration,
            f"Sucesso: {successes}/{num_requests}, Throughput: {throughput:.2f} req/s",
            {
                "total_requests": num_requests,
                "successes": successes,
                "failures": failures,
                "avg_latency_ms": f"{avg_latency:.2f}",
                "min_latency_ms": f"{min_latency:.2f}",
                "max_latency_ms": f"{max_latency:.2f}",
                "p95_latency_ms": f"{p95_latency:.2f}",
                "throughput_rps": f"{throughput:.2f}",
                "node_distribution": node_assignments
            }
        )

        return passed

    async def _submit_request_async(self, session: aiohttp.ClientSession,
                                    request_id: int) -> Optional[dict]:
        """Submete uma requisição assíncrona."""
        url = f"{self.base_url}/v1/analyze-pytorch"
        start = time.time()

        try:
            data = aiohttp.FormData()
            data.add_field("file", self.test_image,
                          filename=f"test_{request_id}.png",
                          content_type="image/png")

            async with session.post(url, data=data, timeout=30) as response:
                latency = (time.time() - start) * 1000

                if response.status == 202:
                    resp_data = await response.json()
                    return {
                        "success": True,
                        "latency_ms": latency,
                        "request_id": resp_data.get("request_id"),
                        "assigned_to_node": resp_data.get("assigned_to_node")
                    }
                return None
        except Exception as e:
            return None

    def test_load_balancing(self, num_requests: int = 30) -> bool:
        """Testa se o balanceamento de carga está funcionando."""
        print(f"\n=== Teste de Balanceamento de Carga ({num_requests} requisições) ===")

        node_assignments = {1: 0, 2: 0, 3: 0, None: 0}
        start = time.time()

        for i in range(num_requests):
            url = f"{self.base_url}/v1/analyze-pytorch"
            try:
                files = {"file": (f"test_{i}.png", self.test_image, "image/png")}
                response = requests.post(url, files=files, timeout=30)

                if response.status_code == 202:
                    data = response.json()
                    node = data.get("assigned_to_node")
                    if node in node_assignments:
                        node_assignments[node] += 1
                    else:
                        node_assignments[None] += 1
            except:
                node_assignments[None] += 1

        duration = (time.time() - start) * 1000

        # Remove contagem de None para análise
        valid_assignments = {k: v for k, v in node_assignments.items() if k is not None}

        if not valid_assignments or sum(valid_assignments.values()) == 0:
            self._record_result(
                "Balanceamento de Carga",
                False,
                duration,
                "Nenhuma tarefa foi distribuída"
            )
            return False

        # Verifica se a distribuição é relativamente uniforme
        values = list(valid_assignments.values())
        avg = sum(values) / len(values) if values else 0

        # Considera balanceado se nenhum nó tem mais que 2x a média
        is_balanced = all(v <= avg * 2 for v in values) if avg > 0 else False

        self._record_result(
            "Balanceamento de Carga",
            is_balanced,
            duration,
            f"Distribuição: {valid_assignments}",
            {
                "node_assignments": node_assignments,
                "average_per_node": f"{avg:.1f}",
                "is_balanced": is_balanced
            }
        )

        return is_balanced

    # =========================================================================
    # TESTES AVANÇADOS
    # =========================================================================

    def test_node_direct_communication(self) -> bool:
        """Testa comunicação direta com cada nó individualmente."""
        print("\n=== Teste de Comunicação Direta com Nós ===")
        all_passed = True

        for port in self.node_ports:
            url = f"http://localhost:{port}/v1/analyze-pytorch"
            start = time.time()

            try:
                files = {"file": ("test.jpg", self.test_image, "image/jpeg")}
                response = requests.post(url, files=files, timeout=30)
                duration = (time.time() - start) * 1000

                if response.status_code == 202:
                    data = response.json()
                    self._record_result(
                        f"Comunicação Direta Node {port}",
                        True,
                        duration,
                        f"Request ID: {data.get('request_id')[:8]}...",
                        {"assigned_to": data.get("assigned_to_node")}
                    )
                else:
                    self._record_result(
                        f"Comunicação Direta Node {port}",
                        False,
                        duration,
                        f"Status: {response.status_code}"
                    )
                    all_passed = False
            except Exception as e:
                duration = (time.time() - start) * 1000
                self._record_result(
                    f"Comunicação Direta Node {port}",
                    False,
                    duration,
                    f"Erro: {str(e)}"
                )
                all_passed = False

        return all_passed

    def test_grpc_connectivity(self) -> bool:
        """Testa se os nós estão se comunicando via gRPC verificando alive_nodes."""
        print("\n=== Teste de Conectividade gRPC ===")

        start = time.time()
        all_nodes_connected = True

        for port in self.node_ports:
            url = f"http://localhost:{port}/v1/distributed/status"
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    alive_nodes = data.get("alive_nodes", [])

                    # Cada nó deve ver todos os 3 nós como vivos
                    if len(alive_nodes) == 3:
                        continue
                    else:
                        all_nodes_connected = False
                        break
            except:
                all_nodes_connected = False
                break

        duration = (time.time() - start) * 1000

        self._record_result(
            "Conectividade gRPC",
            all_nodes_connected,
            duration,
            "Todos os nós conectados via gRPC" if all_nodes_connected else "Falha na conectividade gRPC",
            {"expected_alive": 3}
        )

        return all_nodes_connected

    def test_lamport_clock_sync(self) -> bool:
        """Testa sincronização dos relógios de Lamport entre os nós."""
        print("\n=== Teste de Sincronização de Relógios ===")

        clocks = {}
        start = time.time()

        for port in self.node_ports:
            url = f"http://localhost:{port}/v1/distributed/status"
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    clocks[port] = data.get("lamport_clock", 0)
            except:
                clocks[port] = None

        duration = (time.time() - start) * 1000

        # Verifica se os relógios estão relativamente sincronizados (diferença < 100)
        valid_clocks = [v for v in clocks.values() if v is not None]

        if len(valid_clocks) >= 2:
            max_diff = max(valid_clocks) - min(valid_clocks)
            is_synced = max_diff < 100

            self._record_result(
                "Sincronização de Relógios",
                is_synced,
                duration,
                f"Diferença máxima: {max_diff}",
                {"clocks": clocks, "max_difference": max_diff}
            )
            return is_synced
        else:
            self._record_result(
                "Sincronização de Relógios",
                False,
                duration,
                "Não foi possível obter relógios de múltiplos nós"
            )
            return False

    def test_task_completion(self) -> bool:
        """Testa se as tarefas são completadas corretamente."""
        print("\n=== Teste de Conclusão de Tarefas ===")

        start = time.time()

        # Submete uma tarefa
        url = f"{self.base_url}/v1/analyze-pytorch"
        try:
            files = {"file": ("test.jpg", self.test_image, "image/jpeg")}
            response = requests.post(url, files=files, timeout=30)

            if response.status_code != 202:
                duration = (time.time() - start) * 1000
                self._record_result(
                    "Conclusão de Tarefa",
                    False,
                    duration,
                    f"Falha ao submeter: {response.status_code}"
                )
                return False

            request_id = response.json().get("request_id")

            # Aguarda a tarefa completar (polling)
            status_url = f"{self.base_url}/v1/status/{request_id}"
            max_attempts = 30
            completed = False

            for _ in range(max_attempts):
                time.sleep(1)
                status_response = requests.get(status_url, timeout=5)
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    if status_data.get("status") == "completed":
                        completed = True
                        break

            duration = (time.time() - start) * 1000

            self._record_result(
                "Conclusão de Tarefa",
                completed,
                duration,
                f"Tarefa {'completada' if completed else 'não completada'} em {duration/1000:.1f}s",
                {"request_id": request_id, "completed": completed}
            )
            return completed

        except Exception as e:
            duration = (time.time() - start) * 1000
            self._record_result(
                "Conclusão de Tarefa",
                False,
                duration,
                f"Erro: {str(e)}"
            )
            return False

    # =========================================================================
    # TESTE DE ELEIÇÃO
    # =========================================================================

    def test_trigger_election(self) -> bool:
        """Testa trigger manual de eleição."""
        print("\n=== Teste de Trigger de Eleição ===")

        # Obtém líder atual
        url = f"http://localhost:8001/v1/distributed/leader"
        try:
            response = requests.get(url, timeout=5)
            initial_leader = response.json().get("leader_id") if response.status_code == 200 else None
        except:
            initial_leader = None

        # Dispara eleição
        url = f"http://localhost:8001/v1/distributed/trigger-election"
        start = time.time()

        try:
            response = requests.post(url, timeout=10)
            duration = (time.time() - start) * 1000

            if response.status_code == 200:
                # Aguarda eleição completar
                time.sleep(5)

                # Verifica novo líder
                url = f"http://localhost:8001/v1/distributed/leader"
                response = requests.get(url, timeout=5)
                new_leader = response.json().get("leader_id") if response.status_code == 200 else None

                self._record_result(
                    "Trigger de Eleição",
                    True,
                    duration,
                    f"Eleição disparada com sucesso",
                    {
                        "initial_leader": initial_leader,
                        "final_leader": new_leader
                    }
                )
                return True
            else:
                self._record_result(
                    "Trigger de Eleição",
                    False,
                    duration,
                    f"Status code: {response.status_code}"
                )
                return False
        except Exception as e:
            duration = (time.time() - start) * 1000
            self._record_result(
                "Trigger de Eleição",
                False,
                duration,
                f"Erro: {str(e)}"
            )
            return False

    # =========================================================================
    # GERAÇÃO DE RELATÓRIO
    # =========================================================================

    def print_summary(self):
        """Imprime resumo dos testes."""
        print("\n" + "=" * 60)
        print("RESUMO DOS TESTES")
        print("=" * 60)

        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total = len(self.results)

        print(f"\nTotal: {total} testes")
        print(f"Passou: {passed} ({100*passed/total:.1f}%)" if total > 0 else "Passou: 0")
        print(f"Falhou: {failed} ({100*failed/total:.1f}%)" if total > 0 else "Falhou: 0")

        if failed > 0:
            print("\nTestes que falharam:")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.name}: {r.message}")

        # Calcula tempo total
        total_time = sum(r.duration_ms for r in self.results)
        print(f"\nTempo total de execução: {total_time:.2f}ms ({total_time/1000:.2f}s)")

        print("=" * 60)

    def export_results_json(self, filename: str = "test_results.json"):
        """Exporta resultados para JSON."""
        results_dict = [
            {
                "name": r.name,
                "passed": r.passed,
                "duration_ms": r.duration_ms,
                "message": r.message,
                "details": r.details
            }
            for r in self.results
        ]

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(results_dict, f, indent=2, ensure_ascii=False)

        print(f"\nResultados exportados para: {filename}")


async def main():
    """Função principal."""
    parser = argparse.ArgumentParser(description="Teste de Desempenho - Skin IA Distribuído")
    parser.add_argument("--host", default="localhost", help="Host do sistema")
    parser.add_argument("--port", type=int, default=80, help="Porta principal (NGINX)")
    parser.add_argument("--test-all", action="store_true", help="Executa todos os testes")
    parser.add_argument("--test-load", action="store_true", help="Executa teste de carga")
    parser.add_argument("--test-election", action="store_true", help="Testa eleição")
    parser.add_argument("--requests", type=int, default=20, help="Número de requisições para teste de carga")
    parser.add_argument("--export-json", action="store_true", help="Exporta resultados para JSON")

    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    tester = DistributedSystemTester(base_url)

    print("=" * 60)
    print("TESTE DE DESEMPENHO - SISTEMA DISTRIBUÍDO SKIN IA")
    print("=" * 60)
    print(f"Base URL: {base_url}")
    print(f"Nós individuais: http://localhost:8001, 8002, 8003")
    print("=" * 60)

    # Testes básicos de conectividade
    tester.test_healthcheck()
    tester.test_distributed_status()

    # Wait for initial election to stabilize
    print("\nWaiting 5 seconds for leader election to stabilize...")
    time.sleep(5)

    # Testes do sistema distribuído
    tester.test_leader_consistency()
    tester.test_grpc_connectivity()
    tester.test_lamport_clock_ordering()
    tester.test_lamport_clock_sync()

    # Testes de submissão e processamento
    tester.test_task_submission()
    tester.test_node_direct_communication()
    tester.test_task_completion()

    # Testes de carga e balanceamento
    await tester.test_concurrent_load(args.requests)
    tester.test_load_balancing(args.requests)

    # Teste de eleição
    tester.test_trigger_election()

    # Resumo
    tester.print_summary()

    # Exporta resultados se solicitado
    if args.export_json:
        tester.export_results_json()

    # Retorna código de saída baseado nos resultados
    failed = sum(1 for r in tester.results if not r.passed)
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    asyncio.run(main())
