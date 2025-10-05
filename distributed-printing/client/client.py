import grpc
from distributed_printing import printing_pb2
from distributed_printing import printing_pb2_grpc
import time
import threading
import random
import os
from concurrent import futures

class Client:
    def __init__(self, client_id, server_host, server_port, client_port, other_clients):
        self.client_id = client_id
        self.server_host = server_host
        self.server_port = server_port
        self.client_port = client_port
        self.other_clients = other_clients
        
        self.lamport_clock = 0
        self.request_queue = []
        self.replies_received = set()
        self.requesting = False
        self.request_number = 0
        self.lock = threading.Lock()
        
        # Setup gRPC channels and stubs
        self.setup_server()
        self.setup_client_stubs()
        
    def setup_server(self):
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        printing_pb2_grpc.add_MutualExclusionServiceServicer_to_server(self, self.server)
        self.server.add_insecure_port(f'[::]:{self.client_port}')
        self.server.start()
        print(f"Client {self.client_id} started on port {self.client_port}", flush=True)
    
    def setup_client_stubs(self):
        self.server_stub = printing_pb2_grpc.PrintingServiceStub(
            grpc.insecure_channel(f'{self.server_host}:{self.server_port}'))
        
        self.client_stubs = {}
        for client_id, (host, port) in self.other_clients.items():
            channel = grpc.insecure_channel(f'{host}:{port}')
            self.client_stubs[client_id] = printing_pb2_grpc.MutualExclusionServiceStub(channel)
    
    def update_clock(self, received_ts):
        with self.lock:
            self.lamport_clock = max(self.lamport_clock, received_ts) + 1
    
    def RequestAccess(self, request, context):
        self.update_clock(request.lamport_timestamp)
        
        with self.lock:
            # If we're not requesting or if the incoming request has higher priority
            if not self.requesting or (request.lamport_timestamp, request.client_id) < (self.lamport_clock, self.client_id):
                return printing_pb2.AccessResponse(
                    access_granted=True,
                    lamport_timestamp=self.lamport_clock
                )
            else:
                self.request_queue.append((request.lamport_timestamp, request.client_id))
                return printing_pb2.AccessResponse(
                    access_granted=False,
                    lamport_timestamp=self.lamport_clock
                )
    
    def ReleaseAccess(self, request, context):
        self.update_clock(request.lamport_timestamp)
        
        with self.lock:
            if (request.lamport_timestamp, request.client_id) in self.request_queue:
                self.request_queue.remove((request.lamport_timestamp, request.client_id))
        return printing_pb2.Empty()
    
    def request_critical_section(self):
        with self.lock:
            self.requesting = True
            self.request_number += 1
            self.lamport_clock += 1
            request_ts = self.lamport_clock
            self.replies_received = set()
            
            # Send request to all other clients
            request = printing_pb2.AccessRequest(
                client_id=self.client_id,
                lamport_timestamp=request_ts,
                request_number=self.request_number
            )
            
            for client_id, stub in self.client_stubs.items():
                try:
                    stub.RequestAccess(request)
                except:
                    print(f"Failed to send request to client {client_id}", flush=True)
        
        # Wait for all replies
        while len(self.replies_received) < len(self.other_clients):
            time.sleep(0.1)
        
        # Enter critical section
        self.use_printer()
        
        # Exit critical section
        with self.lock:
            self.requesting = False
            # Release access for queued requests
            release_msg = printing_pb2.AccessRelease(
                client_id=self.client_id,
                lamport_timestamp=self.lamport_clock,
                request_number=self.request_number
            )
            
            for client_id, stub in self.client_stubs.items():
                try:
                    stub.ReleaseAccess(release_msg)
                except:
                    print(f"Failed to send release to client {client_id}", flush=True)
    
    def use_printer(self):
        print(f"Client {self.client_id} is using the printer", flush=True)
        
        # Prepare print request
        with self.lock:
            self.lamport_clock += 1
            request = printing_pb2.PrintRequest(
                client_id=self.client_id,
                message_content=f"Printing document from client {self.client_id}",
                lamport_timestamp=self.lamport_clock,
                request_number=self.request_number
            )
        
        # Send to print server
        try:
            response = self.server_stub.SendToPrinter(request)
            print(f"Print response: {response.confirmation_message}", flush=True)
        except Exception as e:
            print(f"Failed to print: {str(e)}", flush=True)
        
        time.sleep(1)  # Simulate some work
    
    def start(self):
        while True:
            time.sleep(random.uniform(5, 15))  # Random interval between print jobs
            self.request_critical_section()

def parse_clients(clients_str):
    clients = {}
    for client in clients_str.split(','):
        if ':' in client:
            parts = client.split(':')
            if len(parts) == 2:
                client_id = int(parts[0].split('-')[-1])  # Extract ID from client-1:50052
                clients[client_id] = (parts[0], int(parts[1]))
    return clients

if __name__ == '__main__':
    client_id = int(os.getenv('CLIENT_ID', 1))
    server_host = os.getenv('SERVER_HOST', 'localhost')
    server_port = int(os.getenv('SERVER_PORT', '50051'))
    client_port = int(os.getenv('CLIENT_PORT', '50052'))
    other_clients = parse_clients(os.getenv('OTHER_CLIENTS', ''))
    
    client = Client(client_id, server_host, server_port, client_port, other_clients)
    
    # Start client in a separate thread
    client_thread = threading.Thread(target=client.start, daemon=True)
    client_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"Client {client_id} shutting down...", flush=True)
        client.server.stop(0)
