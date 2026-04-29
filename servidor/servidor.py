import socket
import struct
import math
import os
import hashlib
from threading import Thread

#  CONSTANTES DO PROTOCOLO
TIPO_POST    = 1   # Cliente quer enviar um arquivo ao servidor
TIPO_GET     = 2   # Cliente quer baixar um arquivo do servidor
TIPO_READY   = 3   # Servidor sinaliza pronto para receber upload (POST handshake)
TIPO_RESEND  = 4   # NACK: solicitação de retransmissão seletiva
TIPO_ACK     = 5   # Confirmação de recebimento completo
TIPO_ERROR   = 6   # Mensagem de erro (ex: arquivo não encontrado)
TIPO_HELLO   = 7   # Handshake GET — servidor → cliente: "vou começar a enviar"
TIPO_HELLO_ACK = 8 # Handshake GET — cliente → servidor: "estou pronto, pode enviar"

# Pacote de controle: tipo(1B) | id_arq(4B) | tam_msg(2B) | extensao(8B) | mensagem(256B)
# struct.calcsize("!BIH8s256s") = 271 bytes
FORMATO_CONTROLE = "!BIH8s256s"

# Pacote de dados: id_arq(4B) | seq(4B) | total(4B) | tam_real(2B) |
#                  extensao(8B) | checksum_md5(16B) | payload(1400B)
# struct.calcsize("!IIIH8s16s1400s") = 1438 bytes < MTU Ethernet (1500B)
FORMATO_ARQUIVO  = "!IIIH8s16s1400s"

TAM_CHUNK      = 1400        # Bytes de dados úteis por datagrama
PASTA_SERVIDOR = "servidor"  # Diretório onde os arquivos ficam armazenados

# Parâmetros de timeout e retransmissão
TIMEOUT_ACK       = 3.0   # Segundos que o servidor espera por ACK antes de retransmitir
MAX_TENTATIVAS    = 5     # Número máximo de retransmissões automáticas antes de desistir
TIMEOUT_HANDSHAKE = 5.0   # Segundos aguardando HELLO-ACK do cliente

#  FUNÇÕES AUXILIARES
def calcular_checksum(dados: bytes) -> bytes:
    """Retorna digest MD5 de 16 bytes — algoritmo de verificação de integridade."""
    return hashlib.md5(dados).digest()


def empacotar_extensao(extensao: str) -> bytes:
    """Extensão para campo de 8 bytes fixos, preenchido com \\x00."""
    return extensao.encode("utf-8").ljust(8, b"\x00")[:8]


def empacotar_mensagem(mensagem: str) -> tuple:
    """Retorna (tamanho_real, bytes_de_256B) da mensagem."""
    msg_bytes = mensagem.encode("utf-8")[:256]
    return len(msg_bytes), msg_bytes.ljust(256, b"\x00")


def montar_pacote_controle(tipo, id_arq, mensagem="", extensao=""):
    """Atalho para empacotar pacotes de controle."""
    ext = empacotar_extensao(extensao)
    tam, msg = empacotar_mensagem(mensagem)
    return struct.pack(FORMATO_CONTROLE, tipo, id_arq, tam, ext, msg)

#  ENVIO DE ARQUIVO — GET: servidor → cliente
#  Com handshake + pipelining + timeout duplo
def enviar_arquivo(sock, destino_addr, caminho_arquivo, id_arquivo, extensao):
    """
    Protocolo de envio (GET):
      1. HANDSHAKE: servidor envia HELLO, aguarda HELLO-ACK do cliente.
         Garante que o cliente está pronto antes de disparar os dados.
      2. PIPELINING: envia todos os N pacotes de uma vez (sem stop-and-wait).
      3. TIMEOUT DUPLO:
         - Ao expirar, o servidor verifica se recebeu algum RESEND pendente.
         - Se não recebeu nada, considera que o ACK final se perdeu e retransmite
           todos os pacotes ainda não confirmados (abordagem conservadora).
      4. RETRANSMISSÃO SELETIVA: se recebe RESEND, retransmite só os pedidos.
    """
    try:
        tamanho_total = os.path.getsize(caminho_arquivo)
    except FileNotFoundError:
        print(f"[ERRO] Arquivo '{caminho_arquivo}' não encontrado durante envio.")
        return False

    total_pacotes = math.ceil(tamanho_total / TAM_CHUNK)
    ext_bytes     = empacotar_extensao(extensao)

    # ── Função interna: lê e envia um único pacote de dados ──
    def enviar_pacote(seq: int):
        with open(caminho_arquivo, "rb") as f:
            f.seek((seq - 1) * TAM_CHUNK)
            dados    = f.read(TAM_CHUNK)
            tam_real = len(dados)
            checksum = calcular_checksum(dados)
            payload  = dados.ljust(TAM_CHUNK, b"\x00")
            pacote   = struct.pack(
                FORMATO_ARQUIVO,
                id_arquivo, seq, total_pacotes, tam_real,
                ext_bytes, checksum, payload
            )
            sock.sendto(pacote, destino_addr)
            
    #  FASE 1 — HANDSHAKE GET
    #  Servidor → Cliente: HELLO (avisa que vai enviar)
    #  Cliente → Servidor: HELLO_ACK (confirma que está ouvindo)
    print(f"[HANDSHAKE] Iniciando handshake GET com {destino_addr} | ID={id_arquivo}")
    pkt_hello = montar_pacote_controle(TIPO_HELLO, id_arquivo)

    sock.settimeout(TIMEOUT_HANDSHAKE)
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        sock.sendto(pkt_hello, destino_addr)
        try:
            dados_recv, _ = sock.recvfrom(4096)
            if len(dados_recv) == struct.calcsize(FORMATO_CONTROLE):
                tipo_r, id_r, *_ = struct.unpack(FORMATO_CONTROLE, dados_recv)
                if tipo_r == TIPO_HELLO_ACK and id_r == id_arquivo:
                    print(f"[HANDSHAKE] HELLO-ACK recebido. Cliente pronto. Iniciando envio.")
                    break
        except TimeoutError:
            print(f"[HANDSHAKE] Timeout tentativa {tentativa}/{MAX_TENTATIVAS}. Reenviando HELLO...")
    else:
        print(f"[HANDSHAKE] Cliente não respondeu após {MAX_TENTATIVAS} tentativas. Abortando.")
        sock.settimeout(None)
        return False

    #  FASE 2 — PIPELINING: envia todos os pacotes de uma vez
    print(f"[TX] Enviando {total_pacotes} pacote(s) em pipeline para {destino_addr} | ID={id_arquivo}")
    for seq in range(1, total_pacotes + 1):
        enviar_pacote(seq)
    print(f"[TX] Pipeline completo. Aguardando ACK ou RESEND...")

    #  FASE 3 — LOOP DE CONFIRMAÇÃO + TIMEOUT DUPLO
    #  - RESEND recebido → retransmissão seletiva imediata
    #  - Timeout → retransmissão automática (timeout do emissor)
    sock.settimeout(TIMEOUT_ACK)
    tentativas_timeout = 0

    while True:
        try:
            dados_recv, _ = sock.recvfrom(4096)

            if len(dados_recv) != struct.calcsize(FORMATO_CONTROLE):
                continue

            tipo, id_arq, tam_msg, _, msg_bruta = struct.unpack(FORMATO_CONTROLE, dados_recv)

            if id_arq != id_arquivo:
                continue

            if tipo == TIPO_ACK:
                # Transferência concluída com sucesso
                print(f"[✓] ACK final recebido. Transferência ID={id_arquivo} concluída.")
                tentativas_timeout = 0  # Reseta contador
                break

            elif tipo == TIPO_RESEND:
                # NACK seletivo: cliente listou os pacotes que não chegaram
                lista_str     = msg_bruta[:tam_msg].decode("utf-8")
                seqs_perdidos = [int(s) for s in lista_str.split(",") if s.strip().isdigit()]
                print(f"[RESEND] Cliente pediu {len(seqs_perdidos)} pacote(s): {seqs_perdidos}")
                for seq_p in seqs_perdidos:
                    if 1 <= seq_p <= total_pacotes:
                        enviar_pacote(seq_p)
                tentativas_timeout = 0  # Recebeu sinal de vida, reseta timeout

        except TimeoutError:
            # ── TIMEOUT DO EMISSOR (servidor) ──
            # O servidor não recebeu nem ACK nem RESEND no período definido.
            # Estratégia: reenvia todos os pacotes novamente (retransmissão completa)
            # pois não sabemos quais chegaram sem um RESEND explícito.
            tentativas_timeout += 1
            if tentativas_timeout >= MAX_TENTATIVAS:
                print(f"[TIMEOUT] {MAX_TENTATIVAS} timeouts consecutivos sem resposta. "
                      f"Encerrando ID={id_arquivo}.")
                break
            print(f"[TIMEOUT] Sem resposta do cliente (tentativa {tentativas_timeout}/{MAX_TENTATIVAS}). "
                  f"Retransmitindo todos os {total_pacotes} pacotes...")
            for seq in range(1, total_pacotes + 1):
                enviar_pacote(seq)

    sock.settimeout(None)
    return True

#  RECEPÇÃO DE ARQUIVO — POST: cliente → servidor
#  Com handshake READY, timeout duplo (receptor) e descarte de duplicatas
def receber_arquivo(sock, id_esperado, pasta_destino, nome_original, addr_cliente):
    """
    Protocolo de recepção (POST):
      1. HANDSHAKE: servidor envia READY, cliente começa a enviar dados.
         (READY é enviado pelo handle_requisicao antes desta função)
      2. Recebe pacotes em qualquer ordem, verifica checksum MD5.
      3. DUPLICATA: se pacote já existe no buffer → descarta payload mas reenvia ACK
         (destravar o cliente caso o ACK anterior tenha se perdido).
      4. TIMEOUT RECEPTOR: ao detectar silêncio, calcula faltantes e envia RESEND.
      5. Ao completar, salva arquivo e envia ACK final.
    """
    buffer_pacotes          = {}   # seq → bytes dos dados reais
    total_pacotes_esperados = None
    extensao_final          = "bin"
    tentativas_timeout      = 0

    os.makedirs(pasta_destino, exist_ok=True)
    print(f"[RX] Aguardando dados do upload ID={id_esperado} de {addr_cliente}...")

    # Timeout curto: detecta lacunas rapidamente e dispara RESEND
    sock.settimeout(2.0)

    while True:
        try:
            dados, remetente = sock.recvfrom(4096)

            # ── Pacote de dados (1438 bytes esperados) ──
            if len(dados) != struct.calcsize(FORMATO_ARQUIVO):
                continue

            id_arq, seq, tot, tam_real, ext_bytes, checksum_recv, payload = \
                struct.unpack(FORMATO_ARQUIVO, dados)

            if id_arq != id_esperado:
                continue

            tentativas_timeout = 0  # Chegou pacote: reseta contador de timeouts

            # Inicializa metadados com o primeiro pacote recebido
            if total_pacotes_esperados is None:
                total_pacotes_esperados = tot
                extensao_final = ext_bytes.decode("utf-8").strip("\x00")
                print(f"[RX] Recebendo {tot} pacote(s) | ext=.{extensao_final}")

            # ── TRATAMENTO DE DUPLICATAS ──
            # Se o pacote já está no buffer (ex: cliente reenviou porque nosso ACK se perdeu)
            # descarta o payload (já temos os dados), mas reenvia ACK para destravar o cliente.
            if seq in buffer_pacotes:
                # Verifica se é o pacote final e o buffer está cheio (ACK final perdido)
                if len(buffer_pacotes) == total_pacotes_esperados:
                    print(f"[DUP] Pacote #{seq} duplicado + buffer completo. Reenviando ACK final.")
                    pkt_ack = montar_pacote_controle(TIPO_ACK, id_esperado)
                    sock.sendto(pkt_ack, addr_cliente)
                # else: duplicata no meio — ignora silenciosamente (ainda estamos recebendo)
                continue

            # ── VERIFICAÇÃO DE CHECKSUM MD5 ──
            dados_reais        = payload[:tam_real]
            checksum_calculado = calcular_checksum(dados_reais)

            if checksum_recv != checksum_calculado:
                print(f"[ERRO] Checksum inválido no pacote #{seq} — descartado (será pedido via RESEND).")
                continue

            buffer_pacotes[seq] = dados_reais

            # Recebeu tudo?
            if len(buffer_pacotes) == total_pacotes_esperados:
                break

        except TimeoutError:
            # ── TIMEOUT DO RECEPTOR (servidor no POST) ──
            if total_pacotes_esperados is None:
                # Ainda não chegou o primeiro pacote — pode ser latência alta
                tentativas_timeout += 1
                if tentativas_timeout >= MAX_TENTATIVAS:
                    print(f"[TIMEOUT] Nenhum dado recebido após {MAX_TENTATIVAS} timeouts. Abortando upload.")
                    sock.settimeout(None)
                    return False
                continue

            faltantes = sorted(
                set(range(1, total_pacotes_esperados + 1)) - set(buffer_pacotes.keys())
            )

            if not faltantes:
                break  # Tudo chegou — sai do loop

            tentativas_timeout += 1
            if tentativas_timeout >= MAX_TENTATIVAS:
                print(f"[TIMEOUT] Muitos timeouts sem progresso. Abortando upload ID={id_esperado}.")
                sock.settimeout(None)
                return False

            # Envia RESEND em lotes de 40 sequências (cabe em 256 bytes do campo mensagem)
            print(f"[RESEND] Faltam {len(faltantes)} pacote(s). Solicitando retransmissão... "
                  f"(timeout {tentativas_timeout}/{MAX_TENTATIVAS})")
            for i in range(0, len(faltantes), 40):
                lote      = faltantes[i : i + 40]
                lista_str = ",".join(map(str, lote))
                pkt_resend = montar_pacote_controle(TIPO_RESEND, id_esperado, lista_str)
                sock.sendto(pkt_resend, addr_cliente)

    sock.settimeout(None)

    # ── Monta e salva o arquivo completo ──
    nome_final = os.path.join(pasta_destino, f"{nome_original}.{extensao_final}")
    with open(nome_final, "wb") as f:
        for seq in sorted(buffer_pacotes.keys()):
            f.write(buffer_pacotes[seq])

    print(f"Arquivo salvo: '{nome_final}' | {len(buffer_pacotes)}/{total_pacotes_esperados} segmentos")

    # Envia ACK final ao cliente
    pkt_ack = montar_pacote_controle(TIPO_ACK, id_esperado)
    sock.sendto(pkt_ack, addr_cliente)
    return True

#  HANDLER DE REQUISIÇÃO (executa em Thread dedicada)
def handle_requisicao(tipo, id_arq, nome_arquivo, extensao, addr_cliente):
    """
    Cada requisição ganha sua própria thread + socket UDP exclusivo.

    Por que socket próprio?
      - A porta efêmera atribuída pelo SO isola o tráfego de cada transferência.
      - Dois clientes fazendo GET simultâneo não interferem um no outro.
      - O cliente descobre a porta do worker pela origem do primeiro pacote recebido.
    """
    # Socket exclusivo desta thread — o SO atribui a porta efêmera automaticamente
    sock_worker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tipo_str    = "POST (upload)" if tipo == TIPO_POST else "GET (download)"
    print(f"\n[THREAD] Nova thread: {tipo_str} | ID={id_arq} | "
          f"Arquivo={nome_arquivo}.{extensao} | Cliente={addr_cliente}")

    os.makedirs(PASTA_SERVIDOR, exist_ok=True)

    try:
        if tipo == TIPO_POST:
            # ── HANDSHAKE POST ──
            # Servidor → Cliente: READY  (worker já tem sua porta efêmera)
            # Cliente → Servidor: dados (enviados direto para a porta do worker)
            pkt_ready = montar_pacote_controle(TIPO_READY, id_arq)
            sock_worker.sendto(pkt_ready, addr_cliente)
            print(f"[HANDSHAKE] READY enviado para {addr_cliente}. Aguardando dados...")
            receber_arquivo(sock_worker, id_arq, PASTA_SERVIDOR, nome_arquivo, addr_cliente)

        elif tipo == TIPO_GET:
            caminho = os.path.join(PASTA_SERVIDOR, f"{nome_arquivo}.{extensao}")

            if not os.path.exists(caminho):
                # Arquivo não encontrado: envia ERRO descritivo
                msg_erro = f"Arquivo '{nome_arquivo}.{extensao}' nao encontrado no servidor."
                print(f"[ERRO] {msg_erro}")
                pkt_erro = montar_pacote_controle(TIPO_ERROR, id_arq, msg_erro)
                sock_worker.sendto(pkt_erro, addr_cliente)
            else:
                # enviar_arquivo cuida do handshake HELLO/HELLO-ACK internamente
                enviar_arquivo(sock_worker, addr_cliente, caminho, id_arq, extensao)

    finally:
        sock_worker.close()
        print(f"[THREAD] Thread encerrada — ID={id_arq}\n")

#  LOOP PRINCIPAL — Escuta requisições na porta 12000
os.makedirs(PASTA_SERVIDOR, exist_ok=True)

serverSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
serverSocket.bind(("", 12000))

print("  Servidor UDP — Transferência de Arquivos Confiável")
print("  Porta: 12000  |  Diretório: ./servidor/")
print("  Protocolo: segmentos 1400B | MD5 | Pipelining | Handshake")
print("Aguardando requisições...\n")

while True:
    # Loop principal é APENAS um despachante: recebe requisição e cria thread
    dados, addr = serverSocket.recvfrom(4096)

    if len(dados) != struct.calcsize(FORMATO_CONTROLE):
        continue  # Ignora pacotes malformados

    tipo, id_arq, tam_msg, ext_bytes, msg_bruta = struct.unpack(FORMATO_CONTROLE, dados)

    if tipo not in (TIPO_POST, TIPO_GET):
        continue  # Porta 12000 só aceita requisições iniciais

    extensao     = ext_bytes.decode("utf-8").strip("\x00")
    nome_arquivo = msg_bruta[:tam_msg].decode("utf-8")
    tipo_str     = "POST" if tipo == TIPO_POST else "GET"

    print(f"[MAIN] Requisição {tipo_str} de {addr} | {nome_arquivo}.{extensao} | ID={id_arq}")

    # Thread daemon: encerra automaticamente quando o processo principal sair
    t = Thread(
        target=handle_requisicao,
        args=(tipo, id_arq, nome_arquivo, extensao, addr),
        daemon=True
    )
    t.start()
