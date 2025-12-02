# uAlgoritmos Distribuídos - Skin IA

## Visão Geral

O sistema Skin IA implementa um sistema distribuído completo com 3 nós para análise de imagens de doenças de pele usando IA. Este documento explica cada algoritmo implementado e como ele se aplica na aplicação.

---

## 1. Relógio Lógico de Lamport

**Arquivo:** `Codigo/api/app/distributed/lamport_clock.py`

### O que é?

Um contador lógico que sincroniza a ordem de eventos em sistemas distribuídos, onde não existe um relógio global.

### Como funciona?

- Cada nó mantém um contador que incrementa a cada evento
- Quando envia mensagem: incrementa o contador e envia o timestamp
- Quando recebe mensagem: atualiza para `max(relógio_local, timestamp_recebido) + 1`

### Aplicação no Skin IA

- **Ordena todas as requisições** de análise de imagem entre os 3 nós
- **Sincroniza mensagens** entre nós (eleição, heartbeat)
- **Garante consistência** na ordem de processamento das tarefas

**Exemplo prático:**

```
Nó 1 (relógio=5) envia mensagem de eleição → timestamp=6
Nó 2 (relógio=3) recebe → atualiza para max(3,6)+1 = 7
Nó 3 (relógio=8) envia heartbeat → timestamp=9
```

Os timestamps garantem ordem causal dos eventos.

---

## 2. Algoritmo de Eleição Bully

**Arquivo:** `Codigo/api/app/distributed/election.py`

### O que é?

Um algoritmo que elege automaticamente um nó líder entre os 3 nós. O nó com maior ID sempre vence.

### Como funciona?

1. Quando um nó detecta que o líder falhou, inicia uma eleição
2. Envia mensagem `ELECTION` para todos os nós com ID maior
3. Se recebe `OK` de algum nó, espera por mensagem `COORDINATOR`
4. Se não recebe `OK`, se torna líder e envia `COORDINATOR` para todos
5. O nó com maior ID sempre vence e se torna o líder

### Aplicação no Skin IA

- **Coordena a distribuição de tarefas**: Apenas o líder distribui análises de imagem
- **Recuperação automática**: Se o líder falhar (Nó 3), o Nó 2 assume automaticamente
- **Balanceamento de carga**: O líder seleciona qual nó processará cada imagem

**Cenário prático:**

```
Sistema inicializado:
- Nó 1, Nó 2, Nó 3 (todos iniciam eleição)
- Nó 3 tem maior ID → vence e se torna líder
- Nó 3 distribui as análises de imagem

Nó 3 falha:
- Heartbeat detecta falha
- Nó 2 inicia eleição
- Nó 2 vence (maior ID entre os vivos)
- Nó 2 assume distribuição de tarefas
```

---

## 3. Detecção de Falhas por Heartbeat

**Arquivo:** `Codigo/api/app/distributed/heartbeat.py`

### O que é?

Um mecanismo que monitora continuamente se os outros nós estão funcionando através de "pings" periódicos.

### Como funciona?

- A cada 2 segundos, envia ping para todos os nós
- Aguarda resposta com timeout de 1.5 segundos
- Após 3 falhas consecutivas, declara o nó como falho
- Se o líder falhar, dispara automaticamente uma nova eleição
- Se nó falho voltar, detecta e marca como recuperado

### Aplicação no Skin IA

- **Monitora os 3 nós** continuamente
- **Detecta quando um nó para** de responder (crash, rede, etc.)
- **Inicia eleição automática** quando o líder falha
- **Permite recuperação** quando nó volta online

**Fluxo de monitoramento:**

```
Heartbeat Monitor (a cada 2s):
├─> Ping Nó 1 → OK (200ms)
├─> Ping Nó 2 → OK (150ms)
└─> Ping Nó 3 → TIMEOUT (falha 1/3)

Próximo ciclo:
├─> Ping Nó 1 → OK
├─> Ping Nó 2 → OK
└─> Ping Nó 3 → TIMEOUT (falha 2/3)

Próximo ciclo:
├─> Ping Nó 1 → OK
├─> Ping Nó 2 → OK
└─> Ping Nó 3 → TIMEOUT (falha 3/3) → DECLARADO MORTO
    → Dispara callback on_leader_failed()
    → Inicia nova eleição (Bully)
```

---

## 4. Comunicação RPC (Remote Procedure Call)

**Arquivo:** `Codigo/api/app/distributed/rpc_client.py`

### O que é?

Sistema de comunicação entre nós usando HTTP/JSON para enviar mensagens dos algoritmos distribuídos.

### Como funciona?

- Usa HTTP POST para enviar mensagens assíncronas
- Timeout de 2 segundos por requisição
- Serializa dados em JSON
- Codifica payloads binários (imagens) em Base64

### Endpoints RPC implementados:

```
POST /v1/rpc/ping           → Heartbeat (detectar falhas)
POST /v1/rpc/election       → Mensagens de eleição (ELECTION, OK, COORDINATOR)
POST /v1/rpc/task           → Atribuir tarefa de análise de imagem
```

### Aplicação no Skin IA

- **Heartbeat**: Nó 1 verifica se Nó 2 está vivo
- **Eleição**: Nó 2 envia ELECTION para Nó 3
- **Task**: Líder envia imagem para Nó 2 processar

**Exemplo de mensagem RPC:**

```json
POST http://node2:8000/v1/rpc/task
{
  "sender_id": 3,
  "task_id": "abc123",
  "task_type": "analyze_image",
  "payload": "iVBORw0KGgoAAAANS...",  // imagem em Base64
  "timestamp": 42
}
```

---

## 5. Distribuição de Tarefas (Load Balancing)

**Arquivo:** `Codigo/api/app/distributed/task_distributor.py`

### O que é?

Sistema que distribui análises de imagens entre os 3 nós de forma balanceada.

### Como funciona?

1. **Apenas o líder** distribui tarefas
2. Mantém contador de tarefas pendentes por nó
3. Seleciona nó com **menor carga** (least-loaded)
4. Envia tarefa via RPC
5. Atualiza contador de carga

### Aplicação no Skin IA

- **Balanceamento de carga**: Distribui análises uniformemente
- **Otimização**: Evita sobrecarregar um único nó
- **Escalabilidade**: Processa múltiplas imagens simultaneamente

**Exemplo de balanceamento:**

```
Estado inicial:
- Nó 1: 0 tarefas pendentes
- Nó 2: 0 tarefas pendentes
- Nó 3: 0 tarefas pendentes

Cliente envia imagem 1:
→ Líder escolhe Nó 1 (menor carga: 0)
→ Nó 1: 1 tarefa pendente

Cliente envia imagem 2:
→ Líder escolhe Nó 2 (menor carga: 0)
→ Nó 2: 1 tarefa pendente

Cliente envia imagem 3:
→ Líder escolhe Nó 3 (menor carga: 0)
→ Nó 3: 1 tarefa pendente

Cliente envia imagem 4:
→ Nó 1 terminou (0 pendentes)
→ Líder escolhe Nó 1 (menor carga: 0)
```

---

## 7. Gerenciador de Nó (Orquestrador)

**Arquivo:** `Codigo/api/app/distributed/node_manager.py`

### O que é?

O componente central que integra todos os algoritmos distribuídos e fornece interface unificada.

### Componentes integrados:

```
DistributedNode
├── LamportClock           → Sincronização de eventos
├── BullyElection          → Eleição de líder
├── HeartbeatMonitor       → Detecção de falhas
├── RPCClient              → Comunicação entre nós
└── TaskDistributor        → Distribuição de tarefas
```

### Responsabilidades:

1. Inicializar todos os componentes
2. Rotear mensagens RPC para algoritmo correto
3. Atualizar Relógio de Lamport em cada mensagem
4. Processar fila de tarefas atribuídas
5. Fornecer status do sistema distribuído

### Aplicação no Skin IA

- **Interface única** para o FastAPI interagir com sistema distribuído
- **Coordenação automática** entre todos os algoritmos
- **Processamento de tarefas** distribuído entre os nós

**Fluxo completo de análise de imagem:**

```python
# 1. Cliente envia imagem via API
POST /v1/analyze-pytorch
└─> FastAPI recebe
    └─> distributed_node.submit_image_analysis(task_id, image_bytes)

# 2. Distribuição (apenas se for líder)
├─> TaskDistributor.distribute_task()
│   ├─> Seleciona nó com menor carga (ex: Nó 2)
│   └─> Envia via RPC para Nó 2
│
# 3. Nó 2 recebe tarefa
└─> DistributedNode.handle_task_assignment()
    └─> Adiciona tarefa à fila interna

# 4. Loop de processamento (_process_tasks)
└─> Processa imagem com modelo TensorFlow/PyTorch
    └─> result = await analyze_image(image)
```

---

## Integração com a Aplicação Skin IA

### Configuração (docker-compose.distributed.yml)

```yaml
node1:
  environment:
    ENABLE_DISTRIBUTED: "true"
    NODE_ID: "1"
    NODE_1_ADDRESS: "node1:8000"
    NODE_2_ADDRESS: "node2:8000"
    NODE_3_ADDRESS: "node3:8000"

node2:
  environment:
    NODE_ID: "2"
    # ... mesmos endereços

node3:
  environment:
    NODE_ID: "3"
    # ... mesmos endereços
```

### Endpoints da API

**Status do Sistema:**

```bash
GET /v1/distributed/status
# Retorna: líder atual, nós vivos, relógio Lamport, tarefas processadas
```

**Forçar Eleição (teste):**

```bash
POST /v1/distributed/trigger-election
# Inicia eleição manualmente para demonstração
```

**Submeter Análise:**

```bash
POST /v1/analyze-pytorch
Content-Type: multipart/form-data
file: [imagem.jpg]

# Se distribuído habilitado:
# → Líder distribui para nó com menor carga
# → Nó processa a imagem
# → Retorna resultado
```

---

## Fluxo Completo: Do Cliente ao Resultado

```
1. CLIENTE
   └─> POST /v1/analyze-pytorch (imagem.jpg)
       └─> Nginx Load Balancer (porta 80)
           └─> Qualquer nó (1, 2 ou 3)

2. NÓ RECEPTOR
   ├─> Se não é líder:
   │   └─> Retorna erro ou processa localmente
   │
   └─> Se é líder (ex: Nó 3):
       └─> TaskDistributor.distribute_task()
           ├─> NodeLoad: Nó1=2, Nó2=1, Nó3=3
           └─> Seleciona Nó 2 (menor carga)
               └─> RPC: POST node2:8000/v1/rpc/task

3. NÓ 2 (processador)
   └─> handle_task_assignment()
       └─> Adiciona à fila de tarefas
           └─> _process_tasks() loop

4. PROCESSAMENTO (Nó 2)
   └─> analyze_image(image_bytes)
       ├─> Carrega modelo TensorFlow/PyTorch
       ├─> Preprocessa imagem
       ├─> Executa inferência
       └─> Retorna: {"label": "Melanoma", "confidence": 0.89}

5. RESPOSTA
   └─> Resultado salvo no banco PostgreSQL
       └─> Cliente consulta GET /v1/status/{task_id}
           └─> Retorna: "Melanoma (89% confiança)"
```

---

## Garantias do Sistema

| Propriedade            | Garantia                  | Algoritmo          |
| ---------------------- | ------------------------- | ------------------ |
| **Ordem de eventos**   | Ordem total consistente   | Relógio de Lamport |
| **Eleição de líder**   | Eventualmente convergente | Bully Algorithm    |
| **Detecção de falhas** | 6 segundos máx (3×2s)     | Heartbeat          |
| **Balanceamento**      | Distribuição uniforme     | Least-loaded       |

---

## Benefícios para o Skin IA

1. **Alta Disponibilidade**: Se 1 nó falhar, sistema continua funcionando
2. **Escalabilidade**: Processa 3× mais imagens simultaneamente
3. **Recuperação Automática**: Eleição automática quando líder falha
4. **Balanceamento**: Distribui carga uniformemente entre nós
5. **Monitoramento**: Status em tempo real de todo o cluster

---

## Configurações e Timeouts

```python
# Relógio de Lamport
- Sem timeout (sempre incrementa)

# Eleição Bully
- election_timeout = 3.0 segundos (aguardar OK)
- coordinator_timeout = 5.0 segundos (aguardar COORDINATOR)

# Heartbeat
- heartbeat_interval = 2.0 segundos
- timeout = 1.5 segundos por ping
- failure_threshold = 3 falhas consecutivas

# RPC
- request_timeout = 2.0 segundos
```

---

## Demonstração

Para testar o sistema distribuído:

```bash
# 1. Iniciar sistema
docker-compose -f docker-compose.distributed.yml up --build

# 2. Verificar status
curl http://localhost:80/v1/distributed/status

# 3. Ver líder atual
curl http://localhost:80/v1/distributed/leader

# 4. Forçar eleição (demo)
curl -X POST http://localhost:80/v1/distributed/trigger-election

# 5. Submeter análise
curl -X POST http://localhost:80/v1/analyze-pytorch \
  -F "file=@imagem.jpg" \
  -H "ngrok-skip-browser-warning: true"

# 6. Simular falha (parar Nó 3 - líder)
docker-compose -f docker-compose.distributed.yml stop node3
# → Sistema elege novo líder automaticamente (Nó 2)

# 7. Verificar novo líder
curl http://localhost:80/v1/distributed/leader
# → Deve mostrar node_id: 2
```

---

## Conclusão

O sistema distribuído do Skin IA é uma implementação completa e robusta de algoritmos clássicos de sistemas distribuídos aplicados a um problema real: análise de imagens médicas com IA.

Cada algoritmo tem um papel específico:

- **Lamport**: Ordena eventos
- **Bully**: Elege líder
- **Heartbeat**: Detecta falhas
- **Task Distribution**: Balanceia carga
- **Node Manager**: Orquestra tudo

Juntos, eles fornecem um sistema confiável, escalável e resiliente para processar análises de doenças de pele.
