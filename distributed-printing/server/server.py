import grpc
import time
from distributed_printing import printing_pb2
from distributed_printing import printing_pb2_grpc
from concurrent import futures
import logging

class PrintingService(printing_pb2_grpc.PrintingServiceServicer):
    def SendToPrinter(self, request, context):
        print(f"[TS: {request.lamport_timestamp}] CLIENT {request.client_id}: {request.message_content}", flush=True)
        time.sleep(2)  # Simulate printing time
        return printing_pb2.PrintResponse(
            success=True,
            confirmation_message=f"Document printed successfully for client {request.client_id}",
            lamport_timestamp=request.lamport_timestamp + 1
        )

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    printing_pb2_grpc.add_PrintingServiceServicer_to_server(PrintingService(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    print("Print server started on port 50051", flush=True)
    try:
        while True:
            time.sleep(86400)  # One day in seconds
    except KeyboardInterrupt:
        server.stop(0)

if __name__ == '__main__':
    logging.basicConfig()
    serve()
