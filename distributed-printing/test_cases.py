import grpc
import time
import threading
from concurrent import futures
import printing_pb2, printing_pb2_grpc

# Configuration
SERVER_PORT = 50051
CLIENTS = {
    1: 50052,  # client-1
    2: 50053,  # client-2
    3: 50054   # client-3
}

def get_client_stub(port):
    channel = grpc.insecure_channel(f'localhost:{port}')
    return printing_pb2_grpc.MutualExclusionServiceStub(channel)

def get_print_server_stub():
    channel = grpc.insecure_channel('localhost:50051')
    return printing_pb2_grpc.PrintingServiceStub(channel)

def test_scenario1():
    """Cenário 1: Funcionamento Básico sem Concorrência"""
    print("\n=== Cenário 1: Funcionamento Básico sem Concorrência ===")
    
    # Setup stubs for client A (client 1)
    client_a_stub = get_client_stub(CLIENTS[1])
    print_stub = get_print_server_stub()
    
    # 1. Cliente A solicita acesso à impressão via algoritmo Ricart-Agrawala
    print("1. Cliente A (ID:1) solicita acesso via Ricart-Agrawala")
    
    # 2. Cliente A coordena com outros clientes via MutualExclusionService
    print("2. Coordenando com outros clientes via MutualExclusionService...")
    access_response = client_a_stub.RequestAccess(
        printing_pb2.AccessRequest(
            client_id=1,
            lamport_timestamp=1,
            request_number=1
        )
    )
    
    if access_response.access_granted:
        # 3. Cliente A obtém acesso e envia mensagem para servidor burro
        print("3. Acesso concedido. Enviando mensagem para o servidor de impressão...")
        print_response = print_stub.SendToPrinter(
            printing_pb2.PrintRequest(
                client_id=1,
                message_content="Mensagem de teste do Cliente A",
                lamport_timestamp=2,
                request_number=1
            )
        )
        print(f"4. Resposta do servidor: {print_response.confirmation_message}")
        
        # 5. Cliente A libera acesso para outros clientes
        client_a_stub.ReleaseAccess(
            printing_pb2.AccessRelease(
                client_id=1,
                lamport_timestamp=3,
                request_number=1
            )
        )
        print("5. Acesso liberado para outros clientes")
    else:
        print("Falha: Acesso negado ao Cliente A")

def client_print(client_id, timestamp):
    """Helper function for concurrent testing"""
    stub = get_client_stub(CLIENTS[client_id])
    print_stub = get_print_server_stub()
    
    print(f"   - Client {client_id} requesting access (ts: {timestamp})")
    access_response = stub.RequestAccess(
        printing_pb2.AccessRequest(
            client_id=client_id,
            lamport_timestamp=timestamp,
            request_number=timestamp
        )
    )
    
    if access_response.access_granted:
        print(f"   - Client {client_id} access granted")
        print_response = print_stub.SendToPrinter(
            printing_pb2.PrintRequest(
                client_id=client_id,
                message_content=f"Concurrent print from Client {client_id}",
                lamport_timestamp=timestamp + 1,
                request_number=timestamp
            )
        )
        print(f"   - Client {client_id} print response: {print_response.confirmation_message}")
        
        # Release access
        stub.ReleaseAccess(
            printing_pb2.AccessRelease(
                client_id=client_id,
                lamport_timestamp=timestamp + 2,
                request_number=timestamp
            )
        )
        print(f"   - Client {client_id} released access")
    else:
        print(f"   - Client {client_id} access denied")

def test_scenario2():
    """Cenário 2: Concorrência entre Clientes"""
    print("\n=== Cenário 2: Teste de Concorrência ===")
    
    print("Configurando Cliente C (ID:3) para uso inicial...")
    client_c_stub = get_client_stub(CLIENTS[3])
    print_stub = get_print_server_stub()
    
    # Cliente C obtém acesso primeiro
    print("1. Cliente C (ID:3) obtendo acesso...")
    access_response = client_c_stub.RequestAccess(
        printing_pb2.AccessRequest(
            client_id=3,
            lamport_timestamp=1,
            request_number=1
        )
    )
    
    if not access_response.access_granted:
        print("Erro: Cliente C não conseguiu acesso inicial")
        return
    
    print("2. Cliente C está com acesso. Iniciando Clientes A e B...")
    
    def client_a():
        print("   - Cliente A (ID:1) solicitando acesso...")
        client_stub = get_client_stub(CLIENTS[1])
        response = client_stub.RequestAccess(
            printing_pb2.AccessRequest(
                client_id=1,
                lamport_timestamp=2,  # Timestamp menor que B
                request_number=1
            )
        )
        if response.access_granted:
            print("   - Cliente A obteve acesso (deveria ser o primeiro após C)")
            print_response = print_stub.SendToPrinter(
                printing_pb2.PrintRequest(
                    client_id=1,
                    message_content="Mensagem do Cliente A (deveria ser impressa primeiro)",
                    lamport_timestamp=3,
                    request_number=1
                )
            )
            print(f"   - Cliente A recebeu: {print_response.confirmation_message}")
            
            # Libera acesso
            client_stub.ReleaseAccess(
                printing_pb2.AccessRelease(
                    client_id=1,
                    lamport_timestamp=4,
                    request_number=1
                )
            )
            print("   - Cliente A liberou acesso")
    
    def client_b():
        print("   - Cliente B (ID:2) solicitando acesso...")
        client_stub = get_client_stub(CLIENTS[2])
        response = client_stub.RequestAccess(
            printing_pb2.AccessRequest(
                client_id=2,
                lamport_timestamp=3,  # Timestamp maior que A
                request_number=1
            )
        )
        if response.access_granted:
            print("   - Cliente B obteve acesso (deveria ser o segundo após C)")
            print_response = print_stub.SendToPrinter(
                printing_pb2.PrintRequest(
                    client_id=2,
                    message_content="Mensagem do Cliente B (deveria ser impressa depois)",
                    lamport_timestamp=4,
                    request_number=1
                )
            )
            print(f"   - Cliente B recebeu: {print_response.confirmation_message}")
            
            # Libera acesso
            client_stub.ReleaseAccess(
                printing_pb2.AccessRelease(
                    client_id=2,
                    lamport_timestamp=5,
                    request_number=1
                )
            )
            print("   - Cliente B liberou acesso")
    
    # Inicia Clientes A e B em threads separadas
    with futures.ThreadPoolExecutor() as executor:
        future_a = executor.submit(client_a)
        future_b = executor.submit(client_b)
        
        # Dá tempo para os clientes solicitarem acesso
        time.sleep(2)
        
        # Cliente C libera o acesso
        print("3. Cliente C está liberando o acesso...")
        client_c_stub.ReleaseAccess(
            printing_pb2.AccessRelease(
                client_id=3,
                lamport_timestamp=6,
                request_number=1
            )
        )
        print("4. Cliente C liberou o acesso. Os outros clientes devem prosseguir...")
        
        # Espera os clientes terminarem
        futures.wait([future_a, future_b])
    
    print("\n=== Cenário 2 Concluído ===")
    print("Verifique se as mensagens foram impressas na ordem correta:")
    print("1. Cliente C (primeiro a obter acesso)")
    print("2. Cliente A (menor timestamp após C)")
    print("3. Cliente B (maior timestamp)")

if __name__ == '__main__':
    print("Docker deve estar rodando antes de iniciar os testes\n")
    print("No terminal: docker-compose up --build\n")
    
    input("Pressione Enter para executar o Cenário 1 (Funcionamento Básico): \n")
    test_scenario1()
    
    input("\nPressione Enter para executar o Cenário 2 (Teste de Concorrência): \n")
    test_scenario2()