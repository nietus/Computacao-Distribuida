FROM python:3.9-slim

WORKDIR /app

# Install dependencies first
RUN apt-get update && apt-get install -y \
    protobuf-compiler \
    python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --upgrade pip \
    && pip install grpcio grpcio-tools

# Create a package structure
RUN mkdir -p /app/distributed_printing

# Copy the proto file and generate protobuf files
COPY proto/printing.proto /app/distributed_printing/

# Generate protobuf files in the package directory
RUN cd /app/distributed_printing && \
    python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. printing.proto && \
    sed -i 's/import printing_pb2/from . import printing_pb2/g' /app/distributed_printing/printing_pb2_grpc.py

# Copy the client code
COPY client/client.py /app/

# Add __init__.py to make it a proper package
RUN touch /app/distributed_printing/__init__.py

# Set PYTHONPATH to include the app directory
ENV PYTHONPATH=/app

CMD ["python", "client.py"]
