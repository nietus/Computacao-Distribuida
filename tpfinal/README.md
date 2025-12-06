# Sistema Distribuído - Skin IA

## Visão Geral

Sistema distribuído de análise de imagens dermatológicas com IA, composto por **3 nós** que se comunicam via **gRPC** e implementam algoritmos clássicos de sistemas distribuídos.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ARQUITETURA DO SISTEMA                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│                           ┌──────────────┐                              │
│                           │   CLIENTES   │                              │
│                           │  (Browser)   │                              │
│                           └──────┬───────┘                              │
│                                  │ HTTP (porta 80)                      │
│                                  ▼                                      │
│                      ┌───────────────────────┐                          │
│                      │   NGINX LOAD BALANCER │                          │
│                      │     (least_conn)      │                          │
│                      └───────────┬───────────┘                          │
│                 ┌────────────────┼────────────────┐                     │
│                 │                │                │                     │
│                 ▼                ▼                ▼                     │
│          ┌──────────┐     ┌──────────┐     ┌──────────┐                │
│          │  NÓ 1    │     │  NÓ 2    │     │  NÓ 3    │                │
│          │ HTTP:8001│     │ HTTP:8002│     │ HTTP:8003│                │
│          │ gRPC:50051     │ gRPC:50052     │ gRPC:50053│  ◄── LÍDER    │
│          └────┬─────┘     └────┬─────┘     └────┬─────┘                │
│               │                │                │                       │
│               └────────────────┴────────────────┘                       │
│                    Comunicação gRPC (Protocol Buffers)                  │
│                                                                         │
│          ┌──────────────────────────────────────────────┐               │
│          │              BANCO DE DADOS                  │               │
│          │         PostgreSQL (porta 5432)              │               │
│          └──────────────────────────────────────────────┘               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Componentes do Sistema Distribuído

Cada nó executa os seguintes componentes:

```
┌─────────────────────────────────────────────────────────────┐
│                    DISTRIBUTED NODE                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │  Lamport Clock  │    │  Bully Election │                │
│  │  (ordenação)    │    │  (eleição líder)│                │
│  └─────────────────┘    └─────────────────┘                │
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │    Heartbeat    │    │ Task Distributor│                │
│  │ (det. falhas)   │    │ (balanceamento) │                │
│  └─────────────────┘    └─────────────────┘                │
│                                                             │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   gRPC Client   │    │   gRPC Server   │                │
│  │ (envia msgs)    │    │ (recebe msgs)   │                │
│  └─────────────────┘    └─────────────────┘                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Relógio Lógico de Lamport

**Arquivo:** `Codigo/api/app/distributed/lamport_clock.py`

### Problema

Em sistemas distribuídos não existe um relógio global. Como ordenar eventos?

### Solução

Contador lógico que mantém ordem causal dos eventos.

### Algoritmo

```
┌─────────────────────────────────────────────────────────────┐
│                    REGRAS DO LAMPORT CLOCK                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Evento interno:     contador++                          │
│                                                             │
│  2. Enviar mensagem:    contador++                          │
│                         msg.timestamp = contador            │
│                                                             │
│  3. Receber mensagem:   contador = max(contador,            │
│                                        msg.timestamp) + 1   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Exemplo Prático

```
    NÓ 1              NÓ 2              NÓ 3
    [0]               [0]               [0]
     │                 │                 │
     │ evento          │                 │
    [1]                │                 │
     │                 │                 │
     ├─── msg(1) ─────►│                 │
     │                [2]                │
     │                 │                 │
     │                 ├─── msg(2) ─────►│
     │                 │                [3]
     │                 │                 │
     │◄──────────── msg(3) ─────────────┤
    [4]                │                 │
```

### No Skin IA

- Ordena requisições de análise entre os 3 nós
- Sincroniza mensagens de eleição e heartbeat
- Garante consistência na ordem de processamento

---

## 2. Algoritmo de Eleição Bully

**Arquivo:** `Codigo/api/app/distributed/election.py`

### Problema

Quem coordena a distribuição de tarefas? E se o coordenador falhar?

### Solução

Eleição automática onde o nó com **maior ID sempre vence**.

### Algoritmo

```
┌─────────────────────────────────────────────────────────────┐
│                   ALGORITMO BULLY                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Nó detecta líder falho → inicia eleição                 │
│                                                             │
│  2. Envia ELECTION para todos os nós com ID maior           │
│                                                             │
│  3. Se receber OK de algum nó:                              │
│     → Aguarda mensagem COORDINATOR                          │
│                                                             │
│  4. Se NÃO receber OK (timeout 3s):                         │
│     → Torna-se líder                                        │
│     → Envia COORDINATOR para todos                          │
│                                                             │
│  5. Nó com maior ID sempre vence                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Diagrama de Eleição

```
Cenário: Nó 3 (líder) falha, Nó 1 e Nó 2 detectam

    NÓ 1                   NÓ 2                   NÓ 3 (falho)
      │                      │                        ✗
      │                      │
      ├── ELECTION ─────────►│
      │                      │
      │◄─────── OK ──────────┤
      │                      │
      │                      ├── ELECTION ───────────►✗ (sem resposta)
      │                      │
      │                      │ (timeout, maior ID vivo)
      │                      │
      │◄─── COORDINATOR ─────┤
      │                      │
   FOLLOWER               LEADER                   (offline)
```

### Estados do Nó

```
    ┌───────────┐
    │ FOLLOWER  │◄─────────────────────────────┐
    └─────┬─────┘                              │
          │ detecta líder falho                │
          ▼                                    │
    ┌───────────────┐                          │
    │  PARTICIPANT  │ (em eleição)             │
    └───────┬───────┘                          │
            │                                  │
     ┌──────┴──────┐                           │
     │             │                           │
     ▼             ▼                           │
┌────────┐   ┌──────────┐                      │
│ LEADER │   │ FOLLOWER │──────────────────────┘
└────────┘   └──────────┘
(maior ID)    (recebeu COORDINATOR)
```

### No Skin IA

- Nó 3 inicia como líder (maior ID)
- Se Nó 3 falhar → Nó 2 assume automaticamente
- Apenas o líder distribui tarefas de análise

---

## 3. Detecção de Falhas (Heartbeat)

**Arquivo:** `Codigo/api/app/distributed/heartbeat.py`

### Problema

Como saber se um nó está funcionando?

### Solução

Enviar "pings" periódicos e contar falhas consecutivas.

### Configuração

| Parâmetro             | Valor  | Descrição                  |
| --------------------- | ------ | -------------------------- |
| `heartbeat_interval`  | 2s     | Intervalo entre pings      |
| `timeout`             | 1.5s   | Tempo máximo de espera     |
| `failure_threshold`   | 3      | Falhas para declarar morte |
| **Tempo de detecção** | **6s** | 3 × 2s = 6 segundos        |

### Fluxo de Detecção

```
┌─────────────────────────────────────────────────────────────┐
│                   HEARTBEAT MONITOR                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   A cada 2 segundos:                                        │
│                                                             │
│   ┌──────────────────────────────────────────────────────┐  │
│   │ Para cada nó remoto:                                 │  │
│   │                                                      │  │
│   │   Ping ────► Resposta OK?                            │  │
│   │                │                                     │  │
│   │           ┌────┴────┐                                │  │
│   │           │         │                                │  │
│   │          SIM       NÃO                               │  │
│   │           │         │                                │  │
│   │           ▼         ▼                                │  │
│   │    falhas = 0    falhas++                            │  │
│   │                     │                                │  │
│   │              falhas >= 3?                            │  │
│   │                     │                                │  │
│   │                ┌────┴────┐                           │  │
│   │               SIM       NÃO                          │  │
│   │                │         │                           │  │
│   │                ▼         ▼                           │  │
│   │          NÓ MORTO    continua                        │  │
│   │                │                                     │  │
│   │         era líder?                                   │  │
│   │                │                                     │  │
│   │           ┌────┴────┐                                │  │
│   │          SIM       NÃO                               │  │
│   │           │         │                                │  │
│   │           ▼         ▼                                │  │
│   │    NOVA ELEIÇÃO   (apenas marca)                     │  │
│   │                                                      │  │
│   └──────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Exemplo: Detecção de Falha do Líder

```
Tempo    Nó 1 → Nó 3        Estado
────────────────────────────────────────
0s       Ping → OK          falhas = 0
2s       Ping → OK          falhas = 0
4s       Ping → TIMEOUT     falhas = 1   ◄── Nó 3 falha aqui
6s       Ping → TIMEOUT     falhas = 2
8s       Ping → TIMEOUT     falhas = 3   ◄── DECLARADO MORTO
         │
         └──► on_leader_failed()
              └──► Inicia nova eleição
```

### No Skin IA

- Monitora continuamente os 3 nós
- Detecta falhas em no máximo 6 segundos
- Dispara eleição automática quando líder falha
- Detecta recuperação quando nó volta

---

## 4. Comunicação gRPC

**Arquivos:**

- `Codigo/api/app/distributed/rpc_client.py`
- `Codigo/api/app/distributed/grpc_server.py`
- `Codigo/api/app/distributed/node.proto`

### Por que gRPC?

| HTTP/JSON     | gRPC/Protobuf    |
| ------------- | ---------------- |
| Texto (lento) | Binário (rápido) |
| Sem tipos     | Tipagem forte    |
| Overhead alto | Overhead baixo   |

### Serviços Definidos (node.proto)

```protobuf
service NodeService {
  // Heartbeat - verificar se nó está vivo
  rpc Ping(PingRequest) returns (PingResponse);

  // Eleição - mensagens ELECTION, OK, COORDINATOR
  rpc SendElection(ElectionRequest) returns (ElectionResponse);

  // Tarefas - enviar imagem para processamento
  rpc AssignTask(TaskAssignment) returns (TaskAcknowledgement);

  // Status - consultar estado do nó
  rpc GetStatus(StatusRequest) returns (StatusResponse);
}
```

### Fluxo de Comunicação

```
┌──────────────┐                              ┌──────────────┐
│    NÓ 1      │                              │    NÓ 2      │
│              │                              │              │
│ ┌──────────┐ │     gRPC (porta 50051)       │ ┌──────────┐ │
│ │  Client  │─┼──────────────────────────────┼►│  Server  │ │
│ └──────────┘ │      Protocol Buffers        │ └──────────┘ │
│              │       (serializado)          │              │
│ ┌──────────┐ │                              │ ┌──────────┐ │
│ │  Server  │◄┼──────────────────────────────┼─│  Client  │ │
│ └──────────┘ │                              │ └──────────┘ │
└──────────────┘                              └──────────────┘
```

### Todas as Mensagens Incluem Timestamp Lamport

```python
# Ao enviar mensagem
timestamp = lamport_clock.send_event()  # incrementa
request = TaskAssignment(
    task_id="abc123",
    payload=image_bytes,
    timestamp=timestamp  # ◄── Lamport timestamp
)

# Ao receber mensagem
lamport_clock.receive_event(request.timestamp)  # sincroniza
```

---

## 5. Distribuição de Tarefas

**Arquivo:** `Codigo/api/app/distributed/task_distributor.py`

### Algoritmo: Least-Loaded (Menor Carga)

```
┌─────────────────────────────────────────────────────────────┐
│              DISTRIBUIÇÃO DE TAREFAS                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   1. Apenas o LÍDER distribui tarefas                       │
│                                                             │
│   2. Mantém contador de tarefas pendentes por nó:           │
│      ┌─────────────────────────────────────────────┐        │
│      │  Nó 1: 2 tarefas  │  Nó 2: 0 tarefas  │     │        │
│      │  Nó 3: 1 tarefa   │                   │     │        │
│      └─────────────────────────────────────────────┘        │
│                                                             │
│   3. Nova tarefa → seleciona nó com MENOR carga             │
│      → Nó 2 (0 tarefas)                                     │
│                                                             │
│   4. Envia via gRPC: AssignTask(imagem)                     │
│                                                             │
│   5. Incrementa contador do nó selecionado                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Exemplo de Balanceamento

```
Estado inicial: [Nó1: 0, Nó2: 0, Nó3: 0]

Tarefa 1 → Nó 1 (menor)     [Nó1: 1, Nó2: 0, Nó3: 0]
Tarefa 2 → Nó 2 (menor)     [Nó1: 1, Nó2: 1, Nó3: 0]
Tarefa 3 → Nó 3 (menor)     [Nó1: 1, Nó2: 1, Nó3: 1]
Tarefa 4 → Nó 1 completa    [Nó1: 0, Nó2: 1, Nó3: 1]
         → Nó 1 (menor)     [Nó1: 1, Nó2: 1, Nó3: 1]
```

---

## 6. Fluxo Completo: Análise de Imagem

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    FLUXO DE ANÁLISE DE IMAGEM                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. CLIENTE                                                             │
│     └──► POST /v1/analyze-pytorch (imagem.jpg)                          │
│          └──► Nginx (porta 80)                                          │
│               └──► Qualquer nó (ex: Nó 1)                               │
│                                                                         │
│  2. NÓ 1 (não é líder)                                                  │
│     └──► Encaminha para o líder OU processa localmente                  │
│                                                                         │
│  3. NÓ 3 (LÍDER)                                                        │
│     └──► TaskDistributor.distribute_task()                              │
│          ├──► Verifica cargas: [Nó1: 2, Nó2: 0, Nó3: 1]                 │
│          ├──► Seleciona Nó 2 (menor carga)                              │
│          └──► gRPC: AssignTask(task_id, imagem) → Nó 2                  │
│                                                                         │
│  4. NÓ 2 (WORKER)                                                       │
│     └──► Recebe AssignTask via gRPC                                     │
│          └──► Adiciona à fila de processamento                          │
│               └──► Processa:                                            │
│                    ├──► Carrega modelo TensorFlow/PyTorch               │
│                    ├──► Preprocessa imagem                              │
│                    ├──► Executa inferência                              │
│                    └──► Salva resultado: "Melanoma (89%)"               │
│                                                                         │
│  5. CLIENTE                                                             │
│     └──► GET /v1/status/{task_id}                                       │
│          └──► Retorna: {"label": "Melanoma", "confidence": 0.89}        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Cenários de Falha e Recuperação

### Cenário 1: Líder Falha

```
Tempo    Evento                                    Estado do Sistema
─────────────────────────────────────────────────────────────────────────
0s       Sistema funcionando normalmente           Líder: Nó 3

2s       Nó 3 CRASH!                               Líder: Nó 3 (falho)

4s       Nó 1, Nó 2: Ping Nó 3 → TIMEOUT (1/3)

6s       Nó 1, Nó 2: Ping Nó 3 → TIMEOUT (2/3)

8s       Nó 1, Nó 2: Ping Nó 3 → TIMEOUT (3/3)    Nó 3 declarado MORTO
         └──► on_leader_failed()
         └──► Nó 1 e Nó 2 iniciam eleição

9s       Nó 2 vence eleição (maior ID vivo)        Líder: Nó 2
         └──► Envia COORDINATOR para Nó 1

10s      Sistema funcionando com novo líder        Líder: Nó 2
```

### Cenário 2: Nó Recupera

```
Tempo    Evento                                    Estado do Sistema
─────────────────────────────────────────────────────────────────────────
0s       Sistema com Nó 2 como líder               Líder: Nó 2, Vivos: [1, 2]

5s       Nó 3 volta online                         Nó 3 iniciando...

7s       Nó 3: Ping para Nó 1, Nó 2 → OK          Nó 3 detecta cluster
         └──► Inicia eleição

8s       Nó 3 envia ELECTION para... ninguém      Nó 3 tem maior ID
         (não há nós com ID > 3)
         └──► Nó 3 se torna líder
         └──► Envia COORDINATOR para Nó 1, Nó 2

9s       Sistema restaurado                        Líder: Nó 3, Vivos: [1, 2, 3]
```

---

## Como Executar

### Iniciar o Sistema

```bash
# Navegar para o diretório do projeto
cd tpfinal

# Construir e iniciar todos os serviços
docker-compose -f docker-compose.distributed.yml up --build
```

### Verificar Logs

```bash
# Ver logs de todos os nós
docker-compose -f docker-compose.distributed.yml logs -f

# Ver logs de um nó específico
docker-compose -f docker-compose.distributed.yml logs -f node1
docker-compose -f docker-compose.distributed.yml logs -f node2
docker-compose -f docker-compose.distributed.yml logs -f node3
```

### Parar o Sistema

```bash
docker-compose -f docker-compose.distributed.yml down
```

---

## Demonstrações

### Demo 1: Verificar Status do Sistema

```bash
# Ver estado geral do sistema distribuído
curl http://localhost/v1/distributed/status
```

**Resposta esperada:**

```json
{
  "node_id": 1,
  "is_leader": false,
  "leader_id": 3,
  "lamport_clock": 42,
  "election_state": "follower",
  "alive_nodes": [1, 2, 3],
  "total_nodes": 3
}
```

### Demo 2: Identificar o Líder Atual

```bash
curl http://localhost/v1/distributed/leader
```

**Resposta esperada:**

```json
{
  "node_id": 1,
  "is_leader": false,
  "leader_id": 3,
  "clock": 45
}
```

### Demo 3: Submeter Análise de Imagem

```bash
curl -X POST http://localhost/v1/analyze-pytorch \
  -F "file=@imagem_teste.jpg"
```

**Resposta esperada:**

```json
{
  "status": "pending",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "framework": "pytorch",
  "distributed": true,
  "assigned_to_node": 2,
  "assignment_status": "queued_remote"
}
```

### Demo 4: Forçar uma Eleição

```bash
curl -X POST http://localhost/v1/distributed/trigger-election
```

**Nos logs, você verá:**

```
node1  | INFO - Starting election...
node1  | INFO - Sending ELECTION to node 2
node1  | INFO - Sending ELECTION to node 3
node2  | INFO - Received ELECTION from node 1, sending OK
node3  | INFO - Received ELECTION from node 1, sending OK
node3  | INFO - Starting election (highest priority)
node3  | INFO - No higher nodes, becoming leader
node3  | INFO - Sending COORDINATOR to all nodes
node1  | INFO - Received COORDINATOR, new leader is 3
node2  | INFO - Received COORDINATOR, new leader is 3
```

### Demo 5: Simular Falha do Líder

```bash
# Parar o líder (Nó 3)
docker-compose -f docker-compose.distributed.yml stop node3

# Aguardar ~6-8 segundos para detecção

# Verificar novo líder
curl http://localhost/v1/distributed/leader
```

**Resposta esperada (após eleição):**

```json
{
  "node_id": 2,
  "is_leader": true,
  "leader_id": 2,
  "clock": 127
}
```

**Nos logs:**

```
node1  | WARNING - Heartbeat to node 3 failed (1/3)
node2  | WARNING - Heartbeat to node 3 failed (1/3)
node1  | WARNING - Heartbeat to node 3 failed (2/3)
node2  | WARNING - Heartbeat to node 3 failed (2/3)
node1  | WARNING - Heartbeat to node 3 failed (3/3)
node1  | ERROR - Node 3 declared DEAD
node1  | INFO - Leader failed! Starting election...
node2  | ERROR - Node 3 declared DEAD
node2  | INFO - Leader failed! Starting election...
node2  | INFO - No higher alive nodes, becoming leader
node2  | INFO - Sending COORDINATOR to node 1
node1  | INFO - Received COORDINATOR, new leader is 2
```

### Demo 6: Recuperar o Nó

```bash
# Reiniciar o Nó 3
docker-compose -f docker-compose.distributed.yml start node3

# Aguardar ~5 segundos

# Verificar se Nó 3 voltou a ser líder
curl http://localhost/v1/distributed/leader
```

**Resposta esperada:**

```json
{
  "node_id": 3,
  "is_leader": true,
  "leader_id": 3,
  "clock": 203
}
```

### Demo 7: Teste de Carga (múltiplas imagens)

```bash
# Submeter várias imagens rapidamente
for i in {1..5}; do
  curl -X POST http://localhost/v1/analyze-pytorch \
    -F "file=@imagem_teste.jpg" &
done
wait

# Verificar distribuição nos logs
docker-compose -f docker-compose.distributed.yml logs | grep "assigned_to"
```

**Resultado esperado:** Imagens distribuídas entre os 3 nós.

---

## Endpoints da API

| Método | Endpoint                           | Descrição                   |
| ------ | ---------------------------------- | --------------------------- |
| `GET`  | `/v1/distributed/status`           | Estado completo do sistema  |
| `GET`  | `/v1/distributed/leader`           | Quem é o líder atual        |
| `POST` | `/v1/distributed/trigger-election` | Força nova eleição          |
| `POST` | `/v1/analyze-pytorch`              | Submete imagem para análise |
| `GET`  | `/v1/status/{request_id}`          | Status de uma análise       |

---

## Resumo dos Algoritmos

| Algoritmo             | Propósito                          | Arquivo                           |
| --------------------- | ---------------------------------- | --------------------------------- |
| **Lamport Clock**     | Ordenar eventos sem relógio global | `lamport_clock.py`                |
| **Bully Election**    | Eleger líder automaticamente       | `election.py`                     |
| **Heartbeat**         | Detectar falhas de nós             | `heartbeat.py`                    |
| **Task Distribution** | Balancear carga entre nós          | `task_distributor.py`             |
| **gRPC**              | Comunicação eficiente entre nós    | `rpc_client.py`, `grpc_server.py` |

---

## Configurações

```python
# Heartbeat
heartbeat_interval = 2.0s      # Intervalo entre pings
timeout = 1.5s                  # Timeout por ping
failure_threshold = 3           # Falhas para declarar morte

# Eleição Bully
election_timeout = 3.0s         # Aguardar resposta OK
coordinator_timeout = 5.0s      # Aguardar COORDINATOR

# Detecção de falha total
max_detection_time = 6.0s       # 3 × 2s = 6 segundos
```

---

## Garantias do Sistema

| Propriedade              | Garantia                 | Como               |
| ------------------------ | ------------------------ | ------------------ |
| **Ordenação de eventos** | Ordem causal consistente | Lamport Clock      |
| **Único líder**          | Sempre um líder ativo    | Bully Algorithm    |
| **Detecção de falhas**   | ≤ 6 segundos             | Heartbeat Monitor  |
| **Balanceamento**        | Distribuição uniforme    | Least-loaded       |
| **Alta disponibilidade** | Tolera N-1 falhas        | Eleição automática |

---

## Benefícios do Sistema Distribuído

1. **Alta Disponibilidade**: Sistema continua funcionando mesmo com falha de 1 ou 2 nós
2. **Escalabilidade**: Processa 3× mais imagens simultaneamente
3. **Recuperação Automática**: Novo líder eleito automaticamente
4. **Balanceamento de Carga**: Distribui trabalho uniformemente
5. **Monitoramento em Tempo Real**: Status do cluster sempre disponível
