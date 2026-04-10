import socket
import struct
import math
import os

server_addr = ('127.0.0.1', 12000)
clientSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

TIPO_POST = 1
TIPO_GET = 2
TIPO_READY = 3
TIPO_RESEND = 4
TIPO_ACK = 5
TIPO_ERROR = 6

FORMATO_CONTROLE = "!BIH8s256s"
FORMATO_ARQUIVO = "!IIIH8s1400s" 
TAM_CHUNK = 1400


def enviar_arquivo(sock, destino_addr, caminho_arquivo, id_arquivo, extensao):
    try:
        tamanho_total = os.path.getsize(caminho_arquivo)
        total_pacotes = math.ceil(tamanho_total / TAM_CHUNK)
    except FileNotFoundError:
        print(f"[ERRO] Arquivo '{caminho_arquivo}' não encontrado.")
        return False

    ext_bytes = extensao.encode('utf-8')
    
    def enviar_pacote(seq):
        with open(caminho_arquivo, "rb") as f:
            f.seek((seq - 1) * TAM_CHUNK)
            dados = f.read(TAM_CHUNK)
            tam_real = len(dados)
            pacote = struct.pack(FORMATO_ARQUIVO, id_arquivo, seq, total_pacotes, tam_real, ext_bytes, dados.ljust(TAM_CHUNK, b'\x00'))
            sock.sendto(pacote, destino_addr)

    print(f"[>] Iniciando envio de {total_pacotes} pacotes...")
    for seq in range(1, total_pacotes + 1):
        enviar_pacote(seq)

    sock.settimeout(3.0) 
    
    while True:
        try:
            dados, addr = sock.recvfrom(2048)
            if len(dados) == struct.calcsize(FORMATO_CONTROLE):
                tipo, id_arq, tam_msg, _, msg_bruta = struct.unpack(FORMATO_CONTROLE, dados)
                
                if tipo == TIPO_ACK and id_arq == id_arquivo:
                    print(f"[✓] Sucesso! Transferência concluída.")
                    break
                    
                elif tipo == TIPO_RESEND and id_arq == id_arquivo:
                    msg_perdidos = msg_bruta[:tam_msg].decode('utf-8')
                    pacotes_perdidos = [int(p) for p in msg_perdidos.split(',')]
                    print(f"[!] Retransmitindo pacotes: {pacotes_perdidos}")
                    for seq_perdido in pacotes_perdidos:
                        enviar_pacote(seq_perdido)
                        
        except TimeoutError:
            print("[?] Aguardando confirmação (ACK) do servidor...")
            
    sock.settimeout(None)
    return True

def receber_arquivo(sock, id_esperado, pasta_destino, nome_original):
    buffer_pacotes = {}
    total_pacotes_esperados = None
    extensao_final = "bin"
    ultimo_addr = None
    
    print(f"[<] Aguardando download do arquivo (ID: {id_esperado})...")
    sock.settimeout(1.5)
    
    while True:
        try:
            dados, addr = sock.recvfrom(2048)
            ultimo_addr = addr # Guarda o endereço de quem está mandando os pacotes
            
            if len(dados) == struct.calcsize(FORMATO_ARQUIVO):
                id_arq, seq, tot, tam_real, ext_bytes, payload = struct.unpack(FORMATO_ARQUIVO, dados)
                
                if id_arq == id_esperado:
                    if total_pacotes_esperados is None:
                        total_pacotes_esperados = tot
                        extensao_final = ext_bytes.decode('utf-8').strip('\x00')
                    
                    buffer_pacotes[seq] = payload[:tam_real]
                    
                    if len(buffer_pacotes) == total_pacotes_esperados:
                        break
                        
        except TimeoutError:
            if total_pacotes_esperados is None:
                continue
                
            recebidos = set(buffer_pacotes.keys())
            esperados = set(range(1, total_pacotes_esperados + 1))
            faltantes = list(esperados - recebidos)
            
            if len(faltantes) == 0:
                break
                
            print(f"[!] Detectada perda. Solicitando {len(faltantes)} pacotes perdidos...")
            str_faltantes = ",".join(map(str, faltantes[:40]))
            msg_bytes = str_faltantes.encode('utf-8')
            
            pacote_resend = struct.pack(FORMATO_CONTROLE, TIPO_RESEND, id_esperado, len(msg_bytes), b'', msg_bytes.ljust(256, b'\x00'))
            if ultimo_addr:
                sock.sendto(pacote_resend, ultimo_addr)

    sock.settimeout(None)
    nome_final = f"{pasta_destino}/{nome_original}.{extensao_final}"
    
    with open(nome_final, "wb") as f:
        for seq in sorted(buffer_pacotes.keys()):
            f.write(buffer_pacotes[seq])
            
    print(f"[✓] Arquivo reconstruído com sucesso: {nome_final}")
    
    # Envia ACK final
    if ultimo_addr:
        pacote_ack = struct.pack(FORMATO_CONTROLE, TIPO_ACK, id_esperado, 0, b'', b''.ljust(256, b'\x00'))
        sock.sendto(pacote_ack, ultimo_addr)
    
    return True

# --- LOOP PRINCIPAL DO CLIENTE ---
while True:
    comando = input("\n[1] POST (Enviar)\n[2] GET (Receber)\n[0] Sair\nEscolha: ")
    if comando == '0':
        break
    if comando not in ['1', '2']:
        continue
        
    tipo = int(comando)
    id_arquivo = int(input("ID do arquivo (Ex: 10): "))
    nome = input("Nome do arquivo (sem extensão): ")
    extensao = input("Extensão (Ex: txt, png): ")
    
    ext_bytes = extensao.encode('utf-8')
    nome_bytes = nome.encode('utf-8')
    pacote_req = struct.pack(FORMATO_CONTROLE, tipo, id_arquivo, len(nome_bytes), ext_bytes, nome_bytes.ljust(256, b'\x00'))
    
    # Envia a requisição inicial para a porta 12000 do servidor
    clientSocket.sendto(pacote_req, server_addr)
    
    if tipo == TIPO_POST:
        print("Aguardando o servidor liberar o envio...")
        clientSocket.settimeout(5.0)
        try:
            resp_dados, server_transfer_addr = clientSocket.recvfrom(2048)
            if len(resp_dados) == struct.calcsize(FORMATO_CONTROLE):
                tipo_resp, id_resp, _, _, _ = struct.unpack(FORMATO_CONTROLE, resp_dados)
                if tipo_resp == TIPO_READY:
                    caminho_local = f"cliente/{nome}.{extensao}"
                    clientSocket.settimeout(None)
                    # Envia os dados para a nova porta temporária (worker) do servidor
                    enviar_arquivo(clientSocket, server_transfer_addr, caminho_local, id_arquivo, extensao)
        except TimeoutError:
            print("[ERRO] O servidor não respondeu. A fila pode estar cheia.")
            clientSocket.settimeout(None)

    elif tipo == TIPO_GET:
        # Fica em escuta. Quem vai mandar os pacotes é a thread worker do servidor
        receber_arquivo(clientSocket, id_arquivo, "cliente", nome)

clientSocket.close()