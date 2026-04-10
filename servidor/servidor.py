import socket
import struct
import math
import os
from queue import Queue
from threading import Thread

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
            print("[?] Aguardando confirmação (ACK) do cliente...")
            
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
            ultimo_addr = addr
            
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


fila_requisicoes = Queue()

def worker_servidor():
    # Socket exclusivo para enviar/receber dados, não bloqueia a porta principal
    sock_transfer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    while True:
        tipo, id_arq, nome_arquivo, extensao, addr_cliente = fila_requisicoes.get()
        print(f"\n[WORKER] Iniciando tarefa do cliente {addr_cliente} | ID: {id_arq}")

        if tipo == TIPO_POST:
            # Avisa o cliente que está pronto para receber
            # O cliente vai descobrir a porta do worker ao receber essa resposta
            pacote_ready = struct.pack(FORMATO_CONTROLE, TIPO_READY, id_arq, 0, b'', b''.ljust(256, b'\x00'))
            sock_transfer.sendto(pacote_ready, addr_cliente)  # Responde pela porta do worker
            receber_arquivo(sock_transfer, id_arq, "servidor", nome_arquivo)

        elif tipo == TIPO_GET:
            caminho = f"servidor/{nome_arquivo}.{extensao}"
            if not os.path.exists(caminho):
                print(f"[ERRO] Arquivo '{caminho}' não encontrado. Notificando cliente...")
                pacote_erro = struct.pack(FORMATO_CONTROLE, TIPO_ERROR, id_arq, 0, b'', b''.ljust(256, b'\x00'))
                sock_transfer.sendto(pacote_erro, addr_cliente)
            else:
                enviar_arquivo(sock_transfer, addr_cliente, caminho, id_arq, extensao)

        fila_requisicoes.task_done()
        print(f"[WORKER] Tarefa concluída. Aguardando próxima na fila...\n")

serverSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
serverSocket.bind(('', 12000))

# Inicia a thread que consome a fila
Thread(target=worker_servidor, daemon=True).start()

print("Servidor UDP iniciado. Aguardando requisições na porta 12000...")

while True:
    dados, addr = serverSocket.recvfrom(2048)
    
    if len(dados) == struct.calcsize(FORMATO_CONTROLE):
        tipo, id_arq, tam_msg, ext_bytes, msg_bruta = struct.unpack(FORMATO_CONTROLE, dados)
        
        if tipo in (TIPO_POST, TIPO_GET):
            extensao = ext_bytes.decode('utf-8').strip('\x00')
            nome_arquivo = msg_bruta[:tam_msg].decode('utf-8')
            
            tipo_str = "POST (Upload)" if tipo == TIPO_POST else "GET (Download)"
            print(f"[FILA] Nova requisição {tipo_str} recebida de {addr}")
            
            fila_requisicoes.put((tipo, id_arq, nome_arquivo, extensao, addr))