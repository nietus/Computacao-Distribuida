"""Entrypoint FastAPI para o MVP do projeto Skin IA com Sistema Distribuído."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from . import hardware
from .db import SessionLocal, init_db
from .models import AnalysisRequest, AnalysisResult, IdempotencyKey, Client
from .security import verify_api_key
from .tasks import analyze_image_async
from .tasks_pytorch import analyze_image_pytorch_async

# Distributed systems imports
from .distributed.node_manager import DistributedNode, create_node_from_env
from .distributed.election import ElectionMessage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Skin IA - Distributed System")
pending_tasks: set[asyncio.Task[None]] = set()

# Distributed node instance (initialized on startup)
distributed_node: DistributedNode | None = None


def get_db():
    """Gerenciar o ciclo de vida de uma sessão de banco para cada requisição."""

    # Abrimos uma sessão por chamada e garantimos o fechamento no ``finally``.
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
async def on_startup() -> None:
    """Inicializar recursos necessários quando a aplicação sobe."""
    global distributed_node

    # Criar as tabelas do banco
    init_db()

    # Criar um cliente padrão se não existir
    db = SessionLocal()
    try:
        from .models import Client
        from argon2 import PasswordHasher

        default_client = db.query(Client).filter_by(id=1).first()
        if not default_client:
            ph = PasswordHasher()
            default_client = Client(
                id=1,
                name="Default Client",
                api_key_hash=ph.hash("default-key"),
                active=True,
            )
            db.add(default_client)
            db.commit()
    except Exception as e:
        logger.error(f"Error creating default client: {e}")
        db.rollback()
    finally:
        db.close()

    # Initialize distributed system if enabled
    if os.getenv("ENABLE_DISTRIBUTED", "false").lower() == "true":
        try:
            logger.info("Initializing distributed system...")
            distributed_node = create_node_from_env()

            # Set callback for task processing (PyTorch)
            async def process_image_task(task_id: str, image_bytes: bytes):
                """Process image analysis task on this node (PyTorch)."""
                logger.info(f"Node {distributed_node.node_id}: Processing task {task_id} (PyTorch)")
                # Call the existing analyze function
                from .tasks_pytorch import analyze_image_pytorch_async
                await analyze_image_pytorch_async(task_id, image_bytes)

            # Set callback for TensorFlow task processing
            async def process_image_task_tensorflow(task_id: str, image_bytes: bytes):
                """Process image analysis task on this node (TensorFlow)."""
                logger.info(f"Node {distributed_node.node_id}: Processing task {task_id} (TensorFlow)")
                # Call the existing analyze function for TensorFlow
                from .tasks import analyze_image_async
                await analyze_image_async(task_id, image_bytes)

            distributed_node.on_task_assigned = process_image_task
            distributed_node.on_task_assigned_tensorflow = process_image_task_tensorflow

            await distributed_node.start()
            logger.info(
                f"Distributed node started: Node {distributed_node.node_id}, "
                f"Leader: {distributed_node.leader_id}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize distributed system: {e}")
            distributed_node = None
    else:
        logger.info("Distributed system disabled (set ENABLE_DISTRIBUTED=true to enable)")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Cleanup resources on shutdown."""
    global distributed_node

    if distributed_node:
        logger.info("Shutting down distributed node...")
        await distributed_node.stop()
        logger.info("Distributed node stopped")


@app.post("/v1/analyze", status_code=status.HTTP_202_ACCEPTED)
async def analyze(
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """Receber uma imagem, enfileirar a análise assíncrona e retornar o ID."""

    # Lemos o conteúdo do arquivo enviado; FastAPI nos entrega ``UploadFile``.
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo vazio.")

    # Criamos o registro inicial da requisição marcando como ``queued``.
    request = AnalysisRequest(client_id=1, status="queued")  # Using default client ID 1
    db.add(request)
    db.commit()
    db.refresh(request)

    # Use distributed system if enabled, otherwise process locally
    if distributed_node:
        # Submit to distributed system (TensorFlow)
        try:
            assignment = await distributed_node.submit_image_analysis_tensorflow(
                task_id=request.id,
                image_bytes=content
            )
            logger.info(
                f"Task {request.id} assigned to node {assignment.get('assigned_to')} "
                f"(status: {assignment.get('status')})"
            )

            return {
                "status": "pending",
                "request_id": request.id,
                "framework": "tensorflow",
                "distributed": True,
                "assigned_to_node": assignment.get("assigned_to"),
                "assignment_status": assignment.get("status"),
                "note": "Using distributed TensorFlow processing"
            }
        except Exception as e:
            logger.error(f"Failed to submit to distributed system: {e}")
            # Fall back to local processing
            pass

    # Disparamos a tarefa assíncrona que executará o modelo de ML (local processing).
    task = asyncio.create_task(analyze_image_async(request.id, content))
    pending_tasks.add(task)
    task.add_done_callback(pending_tasks.discard)
    return {"status": "pending", "request_id": request.id, "framework": "tensorflow", "distributed": False}


@app.post("/v1/analyze-pytorch", status_code=status.HTTP_202_ACCEPTED)
async def analyze_pytorch(
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    """Receive image and analyze using PyTorch model (optimized, 13.6× faster)."""

    # Read uploaded file content
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file.")

    # Create initial request record marked as queued
    request = AnalysisRequest(client_id=1, status="queued")  # Using default client ID 1
    db.add(request)
    db.commit()
    db.refresh(request)

    # Use distributed system if enabled, otherwise process locally
    if distributed_node:
        # Submit to distributed system
        try:
            assignment = await distributed_node.submit_image_analysis(
                task_id=request.id,
                image_bytes=content
            )
            logger.info(
                f"Task {request.id} assigned to node {assignment.get('assigned_to')} "
                f"(status: {assignment.get('status')})"
            )

            return {
                "status": "pending",
                "request_id": request.id,
                "framework": "pytorch",
                "distributed": True,
                "assigned_to_node": assignment.get("assigned_to"),
                "assignment_status": assignment.get("status"),
                "note": "Using distributed PyTorch processing"
            }
        except Exception as e:
            logger.error(f"Distributed submission failed: {e}, falling back to local")
            # Fall through to local processing

    # Local processing (fallback or distributed disabled)
    task = asyncio.create_task(analyze_image_pytorch_async(request.id, content))
    pending_tasks.add(task)
    task.add_done_callback(pending_tasks.discard)

    return {
        "status": "pending",
        "request_id": request.id,
        "framework": "pytorch",
        "distributed": False,
        "note": "Using local PyTorch processing"
    }


@app.get("/v1/status/{request_id}")
def status_endpoint(
    request_id: str,
    db: Session = Depends(get_db),
):
    """Consultar o status de processamento de uma análise previamente criada."""

    request = db.get(AnalysisRequest, request_id)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request_id não encontrado.")

    if request.status == "completed":
        result = db.query(AnalysisResult).filter_by(request_id=request_id).first()
        if result:
            return {"request_id": request_id, "status": request.status, "result": result.to_dict()}

    return {"request_id": request_id, "status": request.status}


@app.get("/healthz")
def healthcheck():
    """Endpoint simples usado para verificar se a API está viva."""
    return {"status": "ok"}


# Pydantic models for registration
class RegisterRequest(BaseModel):
    """Request model for client registration."""
    name: str
    email: str | None = None


class RegisterResponse(BaseModel):
    """Response model for client registration."""
    client_id: int
    name: str
    api_key: str
    message: str


@app.post("/v1/register", status_code=status.HTTP_201_CREATED, response_model=RegisterResponse)
def register_client(
    request: RegisterRequest,
    db: Session = Depends(get_db),
):
    """Register a new client and generate an API key."""
    import secrets
    from argon2 import PasswordHasher

    # Validate name
    if not request.name or len(request.name.strip()) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Client name must be at least 3 characters long."
        )

    # Check if name already exists
    existing_client = db.query(Client).filter(Client.name == request.name.strip()).first()
    if existing_client:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client name already exists. Please choose a different name."
        )

    # Generate a secure random API key
    api_key = f"sk_{secrets.token_urlsafe(32)}"

    # Hash the API key
    ph = PasswordHasher()
    api_key_hash = ph.hash(api_key)

    # Create new client
    new_client = Client(
        name=request.name.strip(),
        api_key_hash=api_key_hash,
        active=True
    )

    db.add(new_client)
    db.commit()
    db.refresh(new_client)

    logger.info(f"New client registered: ID={new_client.id}, Name={new_client.name}")

    return RegisterResponse(
        client_id=new_client.id,
        name=new_client.name,
        api_key=api_key,
        message="Registration successful! Please save your API key - it won't be shown again."
    )


@app.get("/v1/hardware")
def hardware_capabilities():
    """Expor informações sobre o hardware detectado para fins de observabilidade."""

    info = hardware.detect_torch_device()
    return {
        "framework": "torch",
        "device": info.device,
        "platform": info.platform,
        "detail": info.detail,
    }


# ============================================================================
# DISTRIBUTED SYSTEM ENDPOINTS
# ============================================================================

@app.get("/v1/distributed/status")
def distributed_status():
    """
    Get distributed system status.

    Returns information about:
    - Current node ID
    - Leader ID
    - Election state
    - Lamport clock value
    - Alive nodes
    - Node health
    """
    if not distributed_node:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Distributed system not enabled. Set ENABLE_DISTRIBUTED=true"
        )

    return distributed_node.get_status()


@app.get("/v1/distributed/leader")
def get_leader():
    """Get current leader information."""
    if not distributed_node:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Distributed system not enabled"
        )

    return {
        "node_id": distributed_node.node_id,
        "is_leader": distributed_node.is_leader,
        "leader_id": distributed_node.leader_id,
        "clock": distributed_node.clock.time()
    }


@app.post("/v1/distributed/trigger-election")
async def trigger_election():
    """
    Manually trigger a leader election.

    Useful for testing the Bully election algorithm.
    """
    if not distributed_node:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Distributed system not enabled"
        )

    logger.info(f"Node {distributed_node.node_id}: Manual election triggered via API")
    asyncio.create_task(distributed_node.election.start_election())

    return {
        "message": "Election triggered",
        "node_id": distributed_node.node_id
    }


# ============================================================================
# RPC ENDPOINTS (Inter-node communication)
# ============================================================================

@app.post("/v1/rpc/ping")
async def rpc_ping(request: dict):
    """Handle ping/heartbeat RPC from another node."""
    if not distributed_node:
        raise HTTPException(status_code=503, detail="Distributed system not enabled")

    sender_id = request.get("sender_id")
    timestamp = request.get("timestamp")

    # Update Lamport clock
    distributed_node.clock.receive_event(timestamp)

    return {
        "node_id": distributed_node.node_id,
        "status": "ok",
        "timestamp": distributed_node.clock.time()
    }


@app.post("/v1/rpc/election")
async def rpc_election(request: dict):
    """Handle election message RPC from another node."""
    if not distributed_node:
        raise HTTPException(status_code=503, detail="Distributed system not enabled")

    sender_id = request.get("sender_id")
    message_type = request.get("message_type")
    timestamp = request.get("timestamp")

    # Create ElectionMessage object and delegate to DistributedNode handler
    msg = ElectionMessage(
        sender_id=sender_id,
        message_type=message_type,
        timestamp=timestamp
    )
    await distributed_node.handle_election_message(msg)

    return {"acknowledged": True}


@app.post("/v1/rpc/task")
async def rpc_task(request: dict):
    """Handle task assignment RPC from another node."""
    if not distributed_node:
        raise HTTPException(status_code=503, detail="Distributed system not enabled")

    import base64

    sender_id = request.get("sender_id")
    task_id = request.get("task_id")
    task_type = request.get("task_type")
    payload_b64 = request.get("payload")
    timestamp = request.get("timestamp")

    # Update Lamport clock
    distributed_node.clock.receive_event(timestamp)

    # Decode payload
    payload = base64.b64decode(payload_b64)

    # Process task based on type
    if task_type == "analyze_image" and distributed_node.on_task_assigned:
        asyncio.create_task(distributed_node.on_task_assigned(task_id, payload))

    return {
        "task_id": task_id,
        "accepted": True,
        "message": "Task accepted"
    }
