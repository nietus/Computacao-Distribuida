FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY Codigo/api/requirements.txt ./requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip \
    && pip install -r requirements.txt

# Model is mounted via docker-compose volume at /app/Artefatos/model/cnn_model.keras
RUN mkdir -p /app/Artefatos/model

COPY Codigo /app/Codigo

# Compile protobuf files for gRPC
RUN python -m grpc_tools.protoc \
    -I/app/Codigo/api/app/distributed \
    --python_out=/app/Codigo/api/app/distributed \
    --grpc_python_out=/app/Codigo/api/app/distributed \
    /app/Codigo/api/app/distributed/node.proto \
    && sed -i 's/^import node_pb2/from . import node_pb2/' /app/Codigo/api/app/distributed/node_pb2_grpc.py

EXPOSE 8000
EXPOSE 50051

CMD ["uvicorn", "Codigo.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
