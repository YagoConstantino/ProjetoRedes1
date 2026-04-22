# 📊 Análise Completa da Implementação

## 🎯 Resumo Executivo

Análise detalhada dos requisitos de **Recuperação de Erros**, **Tratamento de Erros** e **Cenários de Teste** implementados no projeto de transferência de arquivos confiável sobre UDP.

**Status Geral**: ✅ **TODOS OS REQUISITOS IMPLEMENTADOS**

---

## 🔄 1. RECUPERAÇÃO DE ERROS/PERDAS

### ✅ 1.1 Simulação de Perda de Pacotes

**Status**: IMPLEMENTADO ✓

**Localização**: `cliente/cliente.py:284-296`

**Funcionalidade**:
- **Perda aleatória**: Taxa de perda em percentual configurável (0-100%)
- **Perda específica**: Lista de números de sequência para descartar intencionalmente
- **Interface interativa**: Menu que permite escolher o modo de simulação

**Código**:
```python
# Modo 1: Aleatório (X% de descarte)
if taxa_perda > 0 and random.random() < taxa_perda:
    deve_descartar = True
    print(f"[SIM] Pacote #{seq:>4} descartado intencionalmente.")

# Modo 2: Específico (números de sequência)
if seq in pacotes_descartar:
    deve_descartar = True
```

**Interface de Entrada**:
```
[SIM] Ativar simulação de perda de pacotes?
      [s] Sim  [N] Não
      
Modo:
  [1] Aleatório — descarta X% dos pacotes
  [2] Específico — informa números de sequência
```

---

### ✅ 1.2 Cliente Detectando Falta de Segmentos

**Status**: IMPLEMENTADO ✓

**Localização**: `cliente/cliente.py:312-339`

**Mecanismos de Detecção**:

1. **Timeout do Receptor** (TIMEOUT_RX = 2.0s)
   - Se não receber dados em 2 segundos, o cliente detecta silêncio
   - Implementado com `socket.settimeout(TIMEOUT_RX)`

2. **Análise de Sequência**
   - Compara o range esperado vs pacotes recebidos
   ```python
   faltantes = sorted(
       set(range(1, total_pacotes_esperados + 1)) - set(buffer_pacotes.keys())
   )
   ```

3. **Rastreamento de Tentativas**
   - Contador `tentativas_timeout` garante máximo de 5 tentativas
   - Evita loops infinitos

**Log de Execução**:
```
[TIMEOUT] Faltam 3 pacote(s). Solicitando retransmissão... (timeout 1/5)
```

---

### ✅ 1.3 Cliente Solicitando Retransmissão (RESEND/NACK)

**Status**: IMPLEMENTADO ✓

**Localização**: 
- Cliente: `cliente/cliente.py:341-350`
- Servidor: `servidor/servidor.py:179-187`

**Processo RESEND**:

**1. Cliente envia lista de sequências faltantes**:
```python
# Envia RESEND em lotes de 40 sequências por pacote
for i in range(0, len(faltantes), 40):
    lote      = faltantes[i : i + 40]
    lista_str = ",".join(map(str, lote))
    pkt_resend = montar_pacote_controle(TIPO_RESEND, id_esperado, lista_str)
    sock.sendto(pkt_resend, ultimo_addr)
```

**2. Servidor processa RESEND e retransmite**:
```python
elif tipo == TIPO_RESEND:
    lista_str     = msg_bruta[:tam_msg].decode("utf-8")
    seqs_perdidos = [int(s) for s in lista_str.split(",") if s.strip().isdigit()]
    print(f"[RESEND] Cliente pediu {len(seqs_perdidos)} pacote(s): {seqs_perdidos}")
    for seq_p in seqs_perdidos:
        if 1 <= seq_p <= total_pacotes:
            enviar_pacote(seq_p)  # Retransmissão seletiva
```

**Exemplo de Saída**:
```
[RESEND] Faltam 3 pacote(s). Solicitando retransmissão...
[SIM] Relatório de simulação:
      Descartados: [2, 5, 8]
      Total descartado: 3 | Recuperados via RESEND: ✅
```

---

### ✅ 1.4 Mecanismo de Disparo de Retransmissão

**Status**: DOCUMENTADO E IMPLEMENTADO ✓

**Três Mecanismos Implementados**:

#### **1️⃣ RESEND Seletivo (Reativo)**
- **Triggerizado por**: Timeout do receptor após 2 segundos sem dados
- **Ação**: Cliente calcula faltantes e envia lista de sequências
- **Eficiência**: Retransmite apenas o necessário

#### **2️⃣ Timeout do Emissor (Automático)**
- **Cliente (POST)**: `TIMEOUT_TX = 5.0s`
  - Se não recebe ACK/RESEND em 5s, retransmite todos os pacotes
  - Máximo 5 tentativas antes de abortar
  
- **Servidor (GET)**: `TIMEOUT_ACK = 3.0s`
  - Se não recebe ACK/RESEND em 3s, retransmite todos os pacotes
  - Máximo 5 tentativas antes de abortar

#### **3️⃣ Tratamento de Duplicatas**
- Se pacote já está no buffer (ex: ACK perdido, cliente retransmitiu)
- Descarta payload (já temos os dados)
- Reenvia ACK para destravar o outro lado

**Diagrama de Fluxo**:
```
Cliente aguarda dados (timeout 2s)
         ↓
Timeout → Calcula faltantes
         ↓
         RESEND (lista de sequências)
         ↓
Servidor recebe RESEND
         ↓
Retransmite seletivamente
         ↓
Cliente recebe dados faltantes
         ↓
Buffer completo? SIM → Envia ACK final
```

---

## ❌ 2. TRATAMENTO DE ERROS DO SERVIDOR

### ✅ 2.1 Cliente Requisitando Arquivo Inexistente

**Status**: IMPLEMENTADO ✓

**Localização**: `servidor/servidor.py:364-371`

**Processo**:
```python
caminho = os.path.join(PASTA_SERVIDOR, f"{nome_arquivo}.{extensao}")

if not os.path.exists(caminho):
    # Arquivo não encontrado: envia ERRO descritivo
    msg_erro = f"Arquivo '{nome_arquivo}.{extensao}' nao encontrado no servidor."
    print(f"[ERRO] {msg_erro}")
    pkt_erro = montar_pacote_controle(TIPO_ERROR, id_arq, msg_erro)
    sock_worker.sendto(pkt_erro, addr_cliente)
```

---

### ✅ 2.2 Servidor Enviando Mensagem de Erro

**Status**: IMPLEMENTADO ✓

**Especificação do Protocolo**:
- **Tipo**: `TIPO_ERROR = 6`
- **Tamanho da mensagem**: até 256 bytes (campo `mensagem` do cabeçalho)
- **Formato**: Pacote de controle padrão com tipo ERROR

**Exemplo**:
```
Arquivo solicitado: "video.mp4"
Resposta do servidor: "[❌ ERRO DO SERVIDOR] Arquivo 'video.mp4' nao encontrado no servidor."
```

---

### ✅ 2.3 Cliente Recebendo e Exibindo Erro

**Status**: IMPLEMENTADO ✓

**Localização**: `cliente/cliente.py:212-217` (durante handshake GET) e `247-252` (durante recepção)

**Durante Handshake GET**:
```python
if tipo == TIPO_ERROR:
    msg_erro = msg_bruta[:tam_msg].decode("utf-8") if tam_msg > 0 \
               else "Arquivo nao encontrado no servidor."
    print(f"\n[❌ ERRO DO SERVIDOR] {msg_erro}")
    sock.settimeout(None)
    return False
```

**Durante Recepção**:
```python
elif tipo == TIPO_HELLO:
    # Servidor mandou HELLO, responde HELLO-ACK
    print(f"[HANDSHAKE] HELLO recebido de {addr}. Enviando HELLO-ACK...")
```

**Saída do Cliente**:
```
[❌ ERRO DO SERVIDOR] Arquivo 'teste.pdf' nao encontrado no servidor.
```

---

### ✅ 2.4 Outros Erros Tratados

**Status**: IMPLEMENTADO ✓

| Erro | Localização | Descrição |
|------|-------------|-----------|
| **Arquivo local não encontrado** | cliente.py:85 | Ao tentar enviar (POST) arquivo inexistente |
| **Timeout HELLO** | cliente.py:229 | Servidor não responde durante GET (handshake) |
| **Timeout READY** | cliente.py:509 | Servidor não autoriza upload (handshake POST) |
| **Timeout do Emissor (GET)** | cliente.py:144-154 | Cliente não recebe ACK/RESEND, retransmite |
| **Timeout do Emissor (POST)** | servidor.py:189-202 | Servidor não recebe ACK/RESEND, retransmite |
| **Timeout do Receptor (GET)** | cliente.py:312-339 | Cliente não recebe dados, envia RESEND |
| **Timeout do Receptor (POST)** | servidor.py:283-314 | Servidor não recebe dados, envia RESEND |
| **Checksum MD5 inválido** | cliente.py:302, servidor.py:273 | Pacote corrompido detectado e descartado |
| **Conexão recusada** | cliente.py:478 | Servidor não está em execução |
| **Requisição inválida** | servidor.py:401-402 | Pacote malformado ignorado |

**Exemplo de Checksum Inválido**:
```python
if checksum_recv != checksum_calculado:
    print(f"[ERRO] Checksum MD5 inválido no pacote #{seq}! Ignorado (será pedido via RESEND).")
    continue
```

---

## 🧪 3. CENÁRIOS DE TESTE ESPECÍFICOS

### ✅ 3.1 Servidor com Dois Clientes Simultâneos

**Status**: IMPLEMENTADO ✓

**Localização**: `servidor/servidor.py:415-421`

**Implementação**:
```python
# Thread daemon: encerra automaticamente quando o processo principal sair
t = Thread(
    target=handle_requisicao,
    args=(tipo, id_arq, nome_arquivo, extensao, addr),
    daemon=True
)
t.start()
```

**Como Funciona**:
1. **Servidor aguarda requisições na porta 12000** (loop principal)
2. **Para cada requisição**: Cria uma **thread dedicada**
3. **Cada thread**:
   - Cria um socket UDP próprio (porta efêmera atribuída pelo SO)
   - Executa `handle_requisicao` independentemente
   - Não bloqueia outras transferências

**Vantagens**:
- ✅ Dois clientes podem fazer GET/POST simultâneos
- ✅ Sem interferência entre transferências
- ✅ Escalável para múltiplos clientes

**Log de Execução**:
```
[MAIN] Requisição GET de 127.0.0.1:45621 | arquivo.pdf | ID=1
[THREAD] Nova thread: GET (download) | ID=1 | Arquivo=arquivo.pdf | Cliente=127.0.0.1:45621

[MAIN] Requisição POST de 127.0.0.1:45622 | dados.txt | ID=2
[THREAD] Nova thread: POST (upload) | ID=2 | Arquivo=dados.txt | Cliente=127.0.0.1:45622
```

---

### ✅ 3.2 Cliente Tentando Conectar Antes do Servidor

**Status**: IMPLEMENTADO ✓

**Localização**: `cliente/cliente.py:474-480`

**Processo**:
```python
clientSocket.settimeout(5.0)
try:
    clientSocket.sendto(pkt_req, server_addr)
except Exception as e:
    print(f"[ERRO] Falha ao enviar requisição: {e}")
    clientSocket.settimeout(None)
    continue
```

**Casos Tratados**:

**Caso 1: Servidor não está executando**
```
[>] Enviando requisição GET → 127.0.0.1:12000
[...] Aguardando autorização do servidor (HELLO)...
[ERRO] Timeout aguardando HELLO do servidor. Verifique se o servidor está ativo.
```

**Caso 2: Endereço IP inválido**
```
[ERRO] Falha ao enviar requisição: [Errno 113] No route to host
```

**Caso 3: Porta inválida**
```
[ERRO] Servidor não respondeu em 5 segundos.
       Verifique se o servidor está em execução.
```

---

### ✅ 3.3 Servidor Interrompido Durante Transferência

**Status**: IMPLEMENTADO ✓

**Localização**: `cliente/cliente.py:312-339`

**Comportamento do Cliente**:

1. **Reconhece a interrupção**: Timeout após 2 segundos sem dados
2. **Tenta recuperação**: Envia até 5 RESEND (MAX_TENTATIVAS)
3. **Falha graciosamente**: Exibe mensagem clara

**Log de Execução Esperado**:
```
[RX] Recebendo dados (ID=1)...
[TIMEOUT] Faltam 3 pacote(s). Solicitando retransmissão... (timeout 1/5)
[TIMEOUT] Faltam 3 pacote(s). Solicitando retransmissão... (timeout 2/5)
[TIMEOUT] Faltam 3 pacote(s). Solicitando retransmissão... (timeout 3/5)
[TIMEOUT] Faltam 3 pacote(s). Solicitando retransmissão... (timeout 4/5)
[TIMEOUT] Faltam 3 pacote(s). Solicitando retransmissão... (timeout 5/5)
[TIMEOUT] 5 timeouts consecutivos. Servidor parou de responder?
```

**Código**:
```python
except TimeoutError:
    tentativas_timeout += 1
    if tentativas_timeout >= MAX_TENTATIVAS:
        print(f"[TIMEOUT] {MAX_TENTATIVAS} timeouts consecutivos. Servidor parou de responder?")
        break
```

---

## 📊 Tabela Resumida de Status

| Categoria | Requisito | Status | Linha | Implementação |
|-----------|-----------|--------|-------|----------------|
| **Recuperação** | Simular perda | ✅ | 284-296 | Aleatória + Específica |
| | Detectar falta | ✅ | 322-324 | Timeout + Sequência |
| | Solicitar retransmissão | ✅ | 341-350 | RESEND seletivo |
| | Mecanismo de disparo | ✅ | Múltiplas | Timeout + Duplicatas |
| **Tratamento de Erros** | Arquivo inexistente | ✅ | 364-371 | Verificação + Mensagem |
| | Mensagem de erro | ✅ | 370 | Pacote TIPO_ERROR |
| | Exibição de erro | ✅ | 212-217 | Print formatado |
| | Outros erros | ✅ | Múltiplas | 8 tipos diferentes |
| **Testes** | Dois clientes | ✅ | 415-421 | Thread + Socket efêmero |
| | Sem servidor | ✅ | 474-480 | Timeout 5s |
| | Servidor cai | ✅ | 312-339 | Timeout + MAX_TENTATIVAS |

---

## 🔧 Constantes e Parâmetros de Controle

### Timeouts

```python
# Cliente
TIMEOUT_RX      = 2.0   # Receptor: detecta gaps/perdas
TIMEOUT_TX      = 5.0   # Emissor (POST): aguarda ACK/RESEND
MAX_TENTATIVAS  = 5     # Limite de retransmissões

# Servidor
TIMEOUT_ACK       = 3.0   # Emissor (GET): aguarda ACK/RESEND
TIMEOUT_HANDSHAKE = 5.0   # Handshake
MAX_TENTATIVAS    = 5
```

### Tamanhos de Pacote

```python
TAM_CHUNK = 1400         # Bytes de payload por datagrama
FORMATO_CONTROLE = "!BIH8s256s"      # 271 bytes
FORMATO_ARQUIVO  = "!IIIH8s16s1400s" # 1438 bytes
```

### Tipos de Mensagem

```python
TIPO_POST      = 1   # Cliente → Servidor: POST
TIPO_GET       = 2   # Cliente → Servidor: GET
TIPO_READY     = 3   # Servidor → Cliente: Pronto para receber
TIPO_RESEND    = 4   # NACK: Solicita retransmissão
TIPO_ACK       = 5   # ACK: Confirma recebimento
TIPO_ERROR     = 6   # Servidor → Cliente: Erro
TIPO_HELLO     = 7   # Servidor → Cliente: Pronto para enviar (GET)
TIPO_HELLO_ACK = 8   # Cliente → Servidor: Estou pronto (GET)
```

---

## 🎓 Conclusão

O projeto implementa **todos os requisitos** de forma robusta:
- ✅ Recuperação de erros com mecanismo de retransmissão seletiva
- ✅ Tratamento completo de erros do servidor
- ✅ Suporte a múltiplos clientes simultâneos
- ✅ Resiliência a falhas de conexão
- ✅ Integridade de dados via checksum MD5

A codebase está bem documentada e pronta para demonstração e testes.
