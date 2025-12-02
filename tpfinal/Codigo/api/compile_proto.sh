#!/bin/bash
# Compile protobuf files for gRPC communication

echo "Compiling node.proto..."

python -m grpc_tools.protoc \
    -I./app/distributed \
    --python_out=./app/distributed \
    --grpc_python_out=./app/distributed \
    ./app/distributed/node.proto

echo "Proto compilation complete!"
echo "Generated files:"
ls -la ./app/distributed/*_pb2*.py
