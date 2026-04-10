from socket import *
import struct
import os

serverSocket = socket(AF_INET, SOCK_DGRAM)
serverSocket.bind(('', 12000))

# FORMATOS GLOBAIS
FORMATO_ARQUIVO = "!II?H8s1400s" # 1419 bytes
FORMATO_CONTROLE = "!BIH8s256s"  # 271 bytes
TAM_CHUNK = 1400

def enviar_arquivo(sock, destino_addr, caminho_arquivo, id_arquivo, extensao):
    try:
        tamanho_total = os.path.getsize(caminho_arquivo)
    except FileNotFoundError:
        print(f"Erro: Arquivo '{caminho_arquivo}' não encontrado.")
        sock.sendto(b"ERRO: Arquivo nao encontrado no remetente", destino_addr)
        return False

    ext_bytes = extensao.encode('utf-8')
    num_seq = 0

    with open(caminho_arquivo, "rb") as f:
        while True:
            dados = f.read(TAM_CHUNK)
            if not dados:
                break
            
            tam_real = len(dados)
            eh_ultimo = f.tell() >= tamanho_total
            dados_completos = dados.ljust(TAM_CHUNK, b'\x00')
            num_seq += 1
            pacote = struct.pack(FORMATO_ARQUIVO, id_arquivo, num_seq, eh_ultimo, tam_real, ext_bytes, dados_completos)
            sock.sendto(pacote, destino_addr)
            print(f"Pacote {num_seq} com {tam_real} bytes enviado\n")
            
    print(f"[>] Arquivo '{caminho_arquivo}' enviado com sucesso!")
    return True

def receber_arquivo(sock, id_esperado, pasta_destino, nome_original):
    buffer_pacotes = {}
    extensao_final = "bin"

    print(f"[<] Aguardando dados do arquivo ID {id_esperado}...")
    
    while True:
        dados, addr = sock.recvfrom(2048)
        
        if len(dados) < 1419:
            msg = dados.decode('utf-8', errors='ignore')
            print(f"[!] Mensagem do outro lado: {msg}")
            if "ERRO" in msg:
                return False
            continue
            
        id_arq, seq, eh_ultimo, tam_real, ext_bytes, payload = struct.unpack(FORMATO_ARQUIVO, dados)
        
        if id_arq != id_esperado:
            continue
            
        extensao_final = ext_bytes.decode('utf-8').strip('\x00')
        buffer_pacotes[seq] = payload[:tam_real]
        print(f"Pacote {seq} com {tam_real} bytes recebido\n")
        
        if eh_ultimo:
            break

    nome_final = f"{pasta_destino}/{nome_original}.{extensao_final}"
    with open(nome_final, "wb") as f:
        for s in sorted(buffer_pacotes.keys()):
            f.write(buffer_pacotes[s])
            
    print(f"[V] Download completo: {nome_final}")
    return True


print("Servidor aguardando requisições...")

while True:
    dados, addr = serverSocket.recvfrom(2048)
    
    if len(dados) == 271:
        tipo, id_arq, tam_msg, ext_bytes, msg_bruta = struct.unpack(FORMATO_CONTROLE, dados)
        
        extensao = ext_bytes.decode('utf-8').strip('\x00')
        nome_arquivo = msg_bruta[:tam_msg].decode('utf-8')
        
        if tipo == 1:
            print(f"\n[POST] Cliente {addr} quer enviar o arquivo: {nome_arquivo}.{extensao}")
            
            serverSocket.sendto(b"OK_READY", addr)
            
            receber_arquivo(serverSocket, id_arq, "servidor", nome_arquivo)
            
        elif tipo == 2:
            print(f"\n[GET] Cliente {addr} solicitou o arquivo: {nome_arquivo}.{extensao}")
            caminho = f"servidor/{nome_arquivo}.{extensao}"
            
            enviar_arquivo(serverSocket, addr, caminho, id_arq, extensao)