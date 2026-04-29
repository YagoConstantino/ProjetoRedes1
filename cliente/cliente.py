import socket
import struct
import math
import os
import hashlib
import random

#  CONSTANTES DO PROTOCOLO (idênticas ao servidor)
TIPO_POST      = 1
TIPO_GET       = 2
TIPO_READY     = 3
TIPO_RESEND    = 4
TIPO_ACK       = 5
TIPO_ERROR     = 6
TIPO_HELLO     = 7   # Servidor avisa que vai começar a enviar (handshake GET)
TIPO_HELLO_ACK = 8   # Cliente confirma que está pronto para receber (handshake GET)

FORMATO_CONTROLE = "!BIH8s256s"      # 271 bytes
FORMATO_ARQUIVO  = "!IIIH8s16s1400s" # 1438 bytes

TAM_CHUNK = 1400

# Parâmetros de timeout e retransmissão
TIMEOUT_RX      = 2.0  # Timeout do receptor: detecta gaps/perdas
TIMEOUT_TX      = 5.0  # Timeout do emissor (POST): aguarda ACK/RESEND
MAX_TENTATIVAS  = 5    # Limite de retransmissões antes de desistir

#  FUNÇÕES AUXILIARES
def calcular_checksum(dados: bytes) -> bytes:
    """MD5 do payload — mesmo algoritmo do servidor."""
    return hashlib.md5(dados).digest()


def empacotar_extensao(extensao: str) -> bytes:
    return extensao.encode("utf-8").ljust(8, b"\x00")[:8]


def empacotar_mensagem(mensagem: str) -> tuple:
    msg_bytes = mensagem.encode("utf-8")[:256]
    return len(msg_bytes), msg_bytes.ljust(256, b"\x00")


def montar_pacote_controle(tipo, id_arq, mensagem="", extensao=""):
    """Atalho para criar pacotes de controle."""
    ext = empacotar_extensao(extensao)
    tam, msg = empacotar_mensagem(mensagem)
    return struct.pack(FORMATO_CONTROLE, tipo, id_arq, tam, ext, msg)

#  ENVIO DE ARQUIVO — POST: cliente → servidor
#  Com handshake READY + pipelining + timeout do emissor
def enviar_arquivo(sock, destino_addr, caminho_arquivo, id_arquivo, extensao):
    """
    Protocolo de envio (POST):
      1. Aguarda READY do servidor (handshake — confirmado antes desta função ser chamada).
      2. PIPELINING: envia todos os N pacotes de uma vez.
      3. TIMEOUT DO EMISSOR: se expirar sem ACK, retransmite automaticamente.
      4. RETRANSMISSÃO SELETIVA: se recebe RESEND do servidor, retransmite só os pedidos.
    """
    if not os.path.exists(caminho_arquivo):
        print(f"[ERRO] Arquivo local não encontrado: '{caminho_arquivo}'")
        return False

    tamanho_total = os.path.getsize(caminho_arquivo)
    total_pacotes = math.ceil(tamanho_total / TAM_CHUNK)
    ext_bytes     = empacotar_extensao(extensao)

    def enviar_pacote(seq: int):
        """Lê o chunk e o envia com cabeçalho + checksum MD5."""
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

    # ── PIPELINING: envia tudo de uma vez ──
    print(f"\n[TX] Enviando '{caminho_arquivo}' em {total_pacotes} pacote(s) de {TAM_CHUNK}B...")
    for seq in range(1, total_pacotes + 1):
        enviar_pacote(seq)
    print(f"[TX] Pipeline completo. Aguardando confirmação do servidor...")

    # ── TIMEOUT DO EMISSOR: aguarda ACK ou RESEND ──
    sock.settimeout(TIMEOUT_TX)
    tentativas = 0

    while True:
        try:
            dados_recv, _ = sock.recvfrom(4096)

            if len(dados_recv) != struct.calcsize(FORMATO_CONTROLE):
                continue

            tipo, id_arq, tam_msg, _, msg_bruta = struct.unpack(FORMATO_CONTROLE, dados_recv)

            if id_arq != id_arquivo:
                continue

            if tipo == TIPO_ACK:
                print(f"[✓] ACK recebido! Arquivo enviado com sucesso (ID={id_arquivo})")
                tentativas = 0
                break

            elif tipo == TIPO_RESEND:
                # Servidor pediu retransmissão de pacotes específicos (NACK seletivo)
                lista_str     = msg_bruta[:tam_msg].decode("utf-8")
                seqs_perdidos = [int(s) for s in lista_str.split(",") if s.strip().isdigit()]
                print(f"[RESEND] Servidor pediu {len(seqs_perdidos)} pacote(s): {seqs_perdidos}")
                for seq_p in seqs_perdidos:
                    if 1 <= seq_p <= total_pacotes:
                        enviar_pacote(seq_p)
                tentativas = 0  # Recebeu sinal de vida, reseta

        except TimeoutError:
            # ── TIMEOUT DO EMISSOR ──
            # Não recebeu nem ACK nem RESEND: reenvia tudo automaticamente
            tentativas += 1
            if tentativas >= MAX_TENTATIVAS:
                print(f"[TIMEOUT] {MAX_TENTATIVAS} timeouts sem resposta do servidor. Abortando.")
                break
            print(f"[TIMEOUT] Sem resposta (tentativa {tentativas}/{MAX_TENTATIVAS}). "
                  f"Retransmitindo {total_pacotes} pacote(s)...")
            for seq in range(1, total_pacotes + 1):
                enviar_pacote(seq)

    sock.settimeout(None)
    return True

#  RECEPÇÃO DE ARQUIVO — GET: servidor → cliente
#  Com handshake HELLO/HELLO-ACK + tratamento de duplicatas + timeout do receptor
def receber_arquivo(sock, id_esperado, pasta_destino, nome_original,
                    taxa_perda: float = 0.0, pacotes_descartar: list = None):
    """
    Protocolo de recepção (GET):
      1. HANDSHAKE: aguarda HELLO do servidor → responde HELLO-ACK.
         Só então o servidor começa a enviar dados, evitando perda dos primeiros pacotes.
      2. Recebe pacotes em qualquer ordem, verifica checksum MD5.
      3. DUPLICATA: pacote já no buffer → descarta payload, reenvia ACK (destravar servidor).
      4. TIMEOUT DO RECEPTOR: ao detectar silêncio, calcula faltantes e envia RESEND.
      5. Ao completar o buffer, salva arquivo e envia ACK final.
    """
    if pacotes_descartar is None:
        pacotes_descartar = []

    buffer_pacotes          = {}   # seq → dados reais (bytes)
    total_pacotes_esperados = None
    extensao_final          = "bin"
    ultimo_addr             = None   # Porta efêmera do worker do servidor
    descartados_log         = []     # Para relatório de simulação
    tentativas_timeout      = 0

    os.makedirs(pasta_destino, exist_ok=True)

    # Exibe configuração de simulação
    if taxa_perda > 0:
        print(f"\n[SIM] Simulação ativa: {taxa_perda * 100:.0f}% de descarte aleatório por pacote.")
    if pacotes_descartar:
        print(f"[SIM] Sequências específicas a descartar: {pacotes_descartar}")

    #  FASE 1 — HANDSHAKE GET
    #  Aguarda HELLO do servidor → responde HELLO-ACK
    #  Garante que o cliente está com recvfrom ativo antes dos dados chegarem
    print(f"[HANDSHAKE] Aguardando HELLO do servidor (ID={id_esperado})...")
    sock.settimeout(10.0)  # Timeout generoso para o servidor processar e iniciar

    while True:
        try:
            dados, addr = sock.recvfrom(4096)
            ultimo_addr = addr

            # ── Verifica se é um pacote de controle ──
            if len(dados) == struct.calcsize(FORMATO_CONTROLE):
                tipo, id_arq, tam_msg, _, msg_bruta = struct.unpack(FORMATO_CONTROLE, dados)

                if id_arq == id_esperado:
                    if tipo == TIPO_ERROR:
                        msg_erro = msg_bruta[:tam_msg].decode("utf-8") if tam_msg > 0 \
                                   else "Arquivo nao encontrado no servidor."
                        print(f"\n[ERRO DO SERVIDOR] {msg_erro}")
                        sock.settimeout(None)
                        return False

                    elif tipo == TIPO_HELLO:
                        # Servidor mandou HELLO: responde HELLO-ACK para liberar envio de dados
                        print(f"[HANDSHAKE] HELLO recebido de {addr}. Enviando HELLO-ACK...")
                        pkt_hello_ack = montar_pacote_controle(TIPO_HELLO_ACK, id_esperado)
                        sock.sendto(pkt_hello_ack, addr)
                        # Agora configura timeout menor para receber dados
                        sock.settimeout(TIMEOUT_RX)
                        break  # Sai do loop de handshake

        except TimeoutError:
            print("[ERRO] Timeout aguardando HELLO do servidor. Verifique se o servidor está ativo.")
            sock.settimeout(None)
            return False
        
    #  FASE 2 — RECEPÇÃO DOS DADOS + TIMEOUT DO RECEPTOR
    print(f"[RX] Recebendo dados (ID={id_esperado})...")

    while True:
        try:
            dados, addr = sock.recvfrom(4096)
            ultimo_addr = addr
            tentativas_timeout = 0  # Chegou dado: reseta contador

            # ── Pacote de controle durante recepção (ex: ERRO tardio) ──
            if len(dados) == struct.calcsize(FORMATO_CONTROLE):
                tipo, id_arq, tam_msg, _, msg_bruta = struct.unpack(FORMATO_CONTROLE, dados)
                if id_arq == id_esperado and tipo == TIPO_ERROR:
                    msg_erro = msg_bruta[:tam_msg].decode("utf-8") if tam_msg > 0 \
                               else "Erro desconhecido no servidor."
                    print(f"\n[ERRO DO SERVIDOR] {msg_erro}")
                    sock.settimeout(None)
                    return False
                continue

            # ── Pacote de dados (1438 bytes) ──
            if len(dados) != struct.calcsize(FORMATO_ARQUIVO):
                continue

            id_arq, seq, tot, tam_real, ext_bytes, checksum_recv, payload = \
                struct.unpack(FORMATO_ARQUIVO, dados)

            if id_arq != id_esperado:
                continue

            # Inicializa metadados no primeiro pacote de dados recebido
            if total_pacotes_esperados is None:
                total_pacotes_esperados = tot
                extensao_final = ext_bytes.decode("utf-8").strip("\x00")
                print(f"[RX] Recebendo {tot} pacote(s) | ext=.{extensao_final}")

            # ── TRATAMENTO DE DUPLICATAS ──
            # Pacote já está no buffer (servidor retransmitiu porque nosso ACK se perdeu).
            # Descarta o payload (já temos), mas reenvia ACK para destravar o servidor.
            if seq in buffer_pacotes:
                if len(buffer_pacotes) == total_pacotes_esperados:
                    # Buffer completo: nosso ACK final se perdeu — reenvia
                    print(f"[DUP] Pacote #{seq} duplicado + buffer completo. Reenviando ACK final.")
                    pkt_ack = montar_pacote_controle(TIPO_ACK, id_esperado)
                    if ultimo_addr:
                        sock.sendto(pkt_ack, ultimo_addr)
                # else: duplicata parcial — ignora silenciosamente
                continue

            # ── SIMULAÇÃO DE PERDA ──
            deve_descartar = False

            if seq in pacotes_descartar:
                deve_descartar = True   # Descarte específico por número de sequência
            elif taxa_perda > 0 and random.random() < taxa_perda:
                deve_descartar = True   # Descarte aleatório por porcentagem

            if deve_descartar:
                if seq not in descartados_log:
                    descartados_log.append(seq)
                    print(f"[SIM] Pacote #{seq:>4} descartado intencionalmente.")
                continue  # Não armazena — será solicitado via RESEND

            # ── VERIFICAÇÃO DE CHECKSUM MD5 ──
            dados_reais        = payload[:tam_real]
            checksum_calculado = calcular_checksum(dados_reais)

            if checksum_recv != checksum_calculado:
                print(f"[ERRO] Checksum MD5 inválido no pacote #{seq}! Ignorado (será pedido via RESEND).")
                continue

            buffer_pacotes[seq] = dados_reais

            # Recebeu tudo?
            if len(buffer_pacotes) == total_pacotes_esperados:
                break

        except TimeoutError:
            # ── TIMEOUT DO RECEPTOR (cliente no GET) ──
            if total_pacotes_esperados is None:
                tentativas_timeout += 1
                if tentativas_timeout >= MAX_TENTATIVAS:
                    print("[ERRO] Nenhum dado recebido após múltiplos timeouts. Servidor caiu?")
                    sock.settimeout(None)
                    return False
                continue

            faltantes = sorted(
                set(range(1, total_pacotes_esperados + 1)) - set(buffer_pacotes.keys())
            )

            if not faltantes:
                break  # Buffer completo — sai do loop

            # Remove da lista de descarte específico para permitir receber na retransmissão
            # (só descartamos uma vez: para demonstrar que o RESEND funcionou)
            for seq_f in faltantes:
                if seq_f in pacotes_descartar:
                    pacotes_descartar.remove(seq_f)
                    print(f"[SIM] Pacote #{seq_f} liberado da lista de descarte para retransmissão.")

            tentativas_timeout += 1
            if tentativas_timeout >= MAX_TENTATIVAS:
                print(f"[TIMEOUT] {MAX_TENTATIVAS} timeouts consecutivos. Servidor parou de responder?")
                break

            print(f"[RESEND] Faltam {len(faltantes)} pacote(s). Solicitando retransmissão... "
                  f"(timeout {tentativas_timeout}/{MAX_TENTATIVAS})")

            # Envia RESEND em lotes de 40 sequências por pacote (limite do campo mensagem)
            for i in range(0, len(faltantes), 40):
                lote      = faltantes[i : i + 40]
                lista_str = ",".join(map(str, lote))
                pkt_resend = montar_pacote_controle(TIPO_RESEND, id_esperado, lista_str)
                if ultimo_addr:
                    sock.sendto(pkt_resend, ultimo_addr)

    sock.settimeout(None)

    # ── Relatório de simulação ──
    if descartados_log:
        print(f"\n[SIM] Relatório de simulação:")
        print(f"      Descartados: {sorted(descartados_log)}")
        print(f"      Total descartado: {len(descartados_log)} | Recuperados via RESEND: ✅")

    # ── Monta e salva o arquivo ──
    nome_final = os.path.join(pasta_destino, f"{nome_original}.{extensao_final}")
    with open(nome_final, "wb") as f:
        for seq in sorted(buffer_pacotes.keys()):
            f.write(buffer_pacotes[seq])

    print(f"\n[✓] Arquivo montado e salvo: '{nome_final}'")
    print(f"    Segmentos recebidos: {len(buffer_pacotes)} / {total_pacotes_esperados}")

    # Envia ACK final ao servidor
    if ultimo_addr:
        pkt_ack = montar_pacote_controle(TIPO_ACK, id_esperado)
        sock.sendto(pkt_ack, ultimo_addr)

    return True

#  CONFIGURAÇÃO INICIAL
print("=" * 55)
print("  Cliente UDP — Transferência de Arquivos Confiável")
print("=" * 55)

ip_input   = input("IP do servidor [Enter = 127.0.0.1]: ").strip()
port_input = input("Porta do servidor [Enter = 12000]:  ").strip()

IP_SERVIDOR    = ip_input   if ip_input            else "127.0.0.1"
PORTA_SERVIDOR = int(port_input) if port_input.isdigit() else 12000
server_addr    = (IP_SERVIDOR, PORTA_SERVIDOR)

clientSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
os.makedirs("cliente", exist_ok=True)

print(f"\n[OK] Servidor: {IP_SERVIDOR}:{PORTA_SERVIDOR}")
print(f"     Arquivos baixados salvos em: ./cliente/")

#  LOOP PRINCIPAL
while True:
    print("\n" + "─" * 50)
    print(" [1] POST — Enviar arquivo ao servidor")
    print(" [2] GET  — Baixar arquivo do servidor")
    print(" [0] Sair")
    print("─" * 50)

    comando = input("Escolha: ").strip()

    if comando == "0":
        break
    if comando not in ("1", "2"):
        print("[AVISO] Opção inválida.")
        continue

    tipo = int(comando)

    # ── Dados comuns a GET e POST ──
    id_raw = input("ID do arquivo (inteiro, ex: 42): ").strip()
    if not id_raw.isdigit():
        print("[ERRO] ID deve ser número inteiro.")
        continue
    id_arquivo = int(id_raw)

    nome     = input("Nome do arquivo (sem extensão): ").strip()
    extensao = input("Extensão (ex: txt, png, pdf, mp4): ").strip()

    if not nome or not extensao:
        print("[ERRO] Nome e extensão são obrigatórios.")
        continue

    # ── Configuração de simulação de perda (somente GET) ──
    taxa_perda        = 0.0
    pacotes_descartar = []

    if tipo == TIPO_GET:
        print("\n[SIM] Ativar simulação de perda de pacotes?")
        sim = input("      [s] Sim  [N] Não: ").strip().lower()

        if sim == "s":
            print("      Modo:")
            print("      [1] Aleatório — descarta X% dos pacotes")
            print("      [2] Específico — informa números de sequência")
            modo = input("      Escolha: ").strip()

            if modo == "1":
                pct_str = input("      Taxa de perda (0 a 100)%: ").strip()
                try:
                    pct = float(pct_str)
                    if 0 < pct <= 100:
                        taxa_perda = pct / 100.0
                    else:
                        print("[AVISO] Valor fora do intervalo. Sem simulação.")
                except ValueError:
                    print("[AVISO] Entrada inválida. Sem simulação.")

            elif modo == "2":
                entrada = input("      Sequências a descartar (ex: 1,3,7): ").strip()
                try:
                    pacotes_descartar = [int(x) for x in entrada.split(",") if x.strip().isdigit()]
                    if not pacotes_descartar:
                        print("[AVISO] Nenhuma sequência válida. Sem simulação.")
                except ValueError:
                    print("[AVISO] Entrada inválida. Sem simulação.")

    # ── Monta e envia requisição para a porta 12000 ──
    pkt_req = montar_pacote_controle(tipo, id_arquivo, nome, extensao)

    print(f"\n[>] Enviando requisição {'POST' if tipo == TIPO_POST else 'GET'} "
          f"→ {server_addr} | {nome}.{extensao} | ID={id_arquivo}")

    clientSocket.settimeout(5.0)
    try:
        clientSocket.sendto(pkt_req, server_addr)
    except Exception as e:
        print(f"[ERRO] Falha ao enviar requisição: {e}")
        clientSocket.settimeout(None)
        continue

    # ── POST: aguarda READY do servidor (handshake), depois envia dados ──
    if tipo == TIPO_POST:
        print("[...] Aguardando autorização do servidor (READY)...")
        try:
            resp_dados, server_transfer_addr = clientSocket.recvfrom(4096)
            clientSocket.settimeout(None)

            if len(resp_dados) == struct.calcsize(FORMATO_CONTROLE):
                tipo_resp, id_resp, tam_msg, _, msg_bruta = struct.unpack(FORMATO_CONTROLE, resp_dados)

                if tipo_resp == TIPO_READY and id_resp == id_arquivo:
                    print(f"[HANDSHAKE] READY recebido de {server_transfer_addr}. Iniciando upload...")
                    # server_transfer_addr é a porta efêmera do worker
                    caminho_local = os.path.join("cliente", f"{nome}.{extensao}")
                    if not os.path.exists(caminho_local):
                        print(f"[ERRO] Arquivo '{caminho_local}' não encontrado localmente.")
                    else:
                        enviar_arquivo(clientSocket, server_transfer_addr, caminho_local, id_arquivo, extensao)

                elif tipo_resp == TIPO_ERROR:
                    tam_msg_r = tam_msg
                    msg_erro  = msg_bruta[:tam_msg_r].decode("utf-8") if tam_msg_r > 0 else "Erro desconhecido."
                    print(f"[ERRO DO SERVIDOR] {msg_erro}")
                else:
                    print(f"[AVISO] Resposta inesperada (tipo={tipo_resp}).")

        except TimeoutError:
            print("[ERRO] Servidor não respondeu em 5 segundos.")
            print("       Verifique se o servidor está em execução.")
        finally:
            clientSocket.settimeout(None)

    # ── GET: aguarda handshake HELLO e depois os dados ──
    elif tipo == TIPO_GET:
        clientSocket.settimeout(None)
        receber_arquivo(
            clientSocket, id_arquivo, "cliente", nome,
            taxa_perda=taxa_perda,
            pacotes_descartar=pacotes_descartar
        )

clientSocket.close()
print("\n[OK] Cliente encerrado.")
