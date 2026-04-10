from socket import *
import struct
import os

server_addr = ('127.0.0.1', 12000)
clientSocket = socket(AF_INET, SOCK_DGRAM)

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

while True:
    comando = input("\nO que deseja fazer?\n[1] POST (Enviar)\n[2] GET (Receber)\n[0] Sair\nEscolha: ")
    
    if comando == '0':
        break
        
    tipo = int(comando)
    id_arquivo = int(input("ID do arquivo (Ex: 10): "))
    nome = input("Nome do arquivo (sem extensão): ")
    extensao = input("Extensão (Ex: txt, png): ")
    
    ext_bytes = extensao.encode('utf-8')
    nome_bytes = nome.encode('utf-8')
    tam_real = len(nome_bytes)
    nome_pad = nome_bytes[:256].ljust(256, b'\x00')
    
    pacote_req = struct.pack(FORMATO_CONTROLE, tipo, id_arquivo, tam_real, ext_bytes, nome_pad)
    clientSocket.sendto(pacote_req, server_addr)
    
    if tipo == 1:
        print("Aguardando autorização do servidor...")
        resp, addr = clientSocket.recvfrom(2048)
        
        if resp == b"OK_READY":
            caminho_local = f"cliente/{nome}.{extensao}"
            enviar_arquivo(clientSocket, server_addr, caminho_local, id_arquivo, extensao)
        else:
            print(f"Erro ou recusa do servidor: {resp.decode()}")

    elif tipo == 2:
        receber_arquivo(clientSocket, id_arquivo, "cliente", nome)

clientSocket.close()