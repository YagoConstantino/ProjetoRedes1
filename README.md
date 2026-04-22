# 🚀 Transferência de Arquivos Confiável sobre UDP

> **Disciplina**: Redes de Computadores  
> **Objetivo**: Implementar um sistema de transferência de arquivos robusto sobre UDP, simulando mecanismos de confiabilidade do TCP

---

## 📖 Visão Geral do Projeto

Este projeto implementa uma aplicação **cliente-servidor** para transferência de arquivos utilizando o protocolo UDP. O foco está em implementar mecanismos robustos de controle e confiabilidade diretamente sobre UDP, incluindo:

- 🔄 **Recuperação automática de perdas** (RESEND seletivo)
- ⚠️ **Tratamento completo de erros**
- 🔐 **Verificação de integridade** (checksum MD5)
- 📦 **Segmentação eficiente** (1400 bytes por datagrama)
- 🤝 **Handshake duplo** (GET e POST)
- ⚡ **Pipelining** (todos os pacotes em rajada)
- 🧵 **Paralelismo real** (múltiplos clientes simultâneos)

---

## 🏗️ Arquitetura do Sistema

```
┌─────────────────────────────────────────────────────────┐
│                     CLIENTE UDP                         │
│  - Requisita arquivos (GET)                             │
│  - Envia arquivos (POST)                                │
│  - Simula perda de pacotes                              │
│  - Detecta e solicita retransmissão (RESEND)            │
└─────────────────────────────────────────────────────────┘
                           ↓↑
                  Protocolo UDP (porta 12000)
                  - Handshake HELLO/HELLO-ACK
                  - Handshake READY
                  - Pipelining + RESEND
                  - ACK/NACK + Timeouts
                           ↓↑
┌─────────────────────────────────────────────────────────┐
│                    SERVIDOR UDP                         │
│  - Thread por cliente (paralelismo real)                │
│  - Porta efêmera por transferência                      │
│  - Handshake e envio (GET)                              │
│  - Recepção com timeout (POST)                          │
│  - Tratamento de erros (arquivo não encontrado)         │
└─────────────────────────────────────────────────────────┘
```

---

## 🎯 Funcionalidades Principais

### ✅ Lado do Cliente (`cliente/cliente.py`)

| Função | Descrição |
|--------|-----------|
| `receber_arquivo()` | **GET**: Recebe arquivo do servidor com handshake, timeout, RESEND e verificação MD5 |
| `enviar_arquivo()` | **POST**: Envia arquivo para servidor com pipelining, timeout e retransmissão automática |
| Loop Principal | Menu interativo para POST/GET com simulação de perda |

### ✅ Lado do Servidor (`servidor/servidor.py`)

| Função | Descrição |
|--------|-----------|
| `enviar_arquivo()` | **GET**: Envia arquivo com handshake HELLO/HELLO-ACK e retransmissão seletiva |
| `receber_arquivo()` | **POST**: Recebe arquivo com detecção de duplicatas e RESEND |
| `handle_requisicao()` | **Thread worker**: Gerencia uma transferência completa (GET ou POST) |
| Loop Principal | Dispatcher: escuta porta 12000, cria thread para cada requisição |

---

## 🔑 Funções Críticas Explicadas

### 1️⃣ Recepção no Cliente: `receber_arquivo()` (cliente.py:165-374)

**Responsabilidade**: GET — baixar arquivo do servidor com recuperação de perdas

**Fluxo**:
```
1. HANDSHAKE: aguarda HELLO → responde HELLO-ACK
2. Inicia timeout curto (2s) para detectar gaps
3. LOOP DE RECEPÇÃO:
   - Verifica checksum MD5 de cada pacote
   - Trata duplicatas (descarta payload, reenvia ACK)
   - Detecta faltantes via timeout
   - Envia RESEND seletivo se necessário
4. Ao completar: salva arquivo e envia ACK final
```

**Simulação de Perda**:
```python
# Modo 1: Aleatório
if taxa_perda > 0 and random.random() < taxa_perda:
    continue  # Descarta este pacote

# Modo 2: Específico
if seq in pacotes_descartar:
    continue  # Descarta se está na lista
```

**Detecção de Perda**:
```python
faltantes = sorted(
    set(range(1, total_pacotes_esperados + 1)) - set(buffer_pacotes.keys())
)
# Se faltantes não-vazio → envia RESEND
```

---

### 2️⃣ Envio no Cliente: `enviar_arquivo()` (cliente.py:76-157)

**Responsabilidade**: POST — enviar arquivo para servidor com confirmação

**Fluxo**:
```
1. HANDSHAKE: aguarda READY do servidor
2. PIPELINING: envia todos os N pacotes rapidamente
3. LOOP DE CONFIRMAÇÃO:
   - Aguarda ACK (transferência OK)
   - Se recebe RESEND → retransmite seletivamente
   - Se timeout → retransmite todos (até 5x)
4. Completo quando recebe ACK
```

**Pipelining**:
```python
for seq in range(1, total_pacotes + 1):
    enviar_pacote(seq)  # Dispara todos de uma vez
```

**Timeout do Emissor**:
```python
except TimeoutError:
    tentativas += 1
    if tentativas >= MAX_TENTATIVAS:
        print("Abortando após 5 tentativas")
        break
    # Retransmite todos os pacotes
    for seq in range(1, total_pacotes + 1):
        enviar_pacote(seq)
```

---

### 3️⃣ Envio no Servidor: `enviar_arquivo()` (servidor.py:84-205)

**Responsabilidade**: GET — enviar arquivo com handshake robusto

**Fluxo**:
```
1. HANDSHAKE: envia HELLO, aguarda HELLO-ACK
   (garante que cliente está pronto antes de disparar dados)
2. PIPELINING: envia todos os pacotes
3. LOOP DE CONFIRMAÇÃO:
   - Aguarda ACK (sucesso)
   - Se RESEND → retransmite seletivamente
   - Se timeout → retransmite todos (até 5x)
```

**Handshake GET** (crucial):
```python
# Fase 1: envia HELLO
pkt_hello = montar_pacote_controle(TIPO_HELLO, id_arquivo)
sock.sendto(pkt_hello, destino_addr)

# Fase 1a: aguarda HELLO-ACK
sock.settimeout(TIMEOUT_HANDSHAKE)
try:
    dados_recv, _ = sock.recvfrom(4096)
    if tipo_r == TIPO_HELLO_ACK and id_r == id_arquivo:
        print("Cliente pronto. Iniciando envio.")
        break  # Sai do handshake
```

---

### 4️⃣ Recepção no Servidor: `receber_arquivo()` (servidor.py:213-329)

**Responsabilidade**: POST — receber arquivo com detecção de duplicatas

**Fluxo**:
```
1. Aguarda dados com timeout curto (2s)
2. Verifica checksum MD5
3. TRATAMENTO DE DUPLICATA:
   - Se pacote já no buffer:
     * Se buffer completo → reenvia ACK final (pode estar perdido)
     * Senão → ignora silenciosamente
4. Ao completar: salva arquivo e envia ACK final
```

**Tratamento de Duplicata** (estratégia inteligente):
```python
if seq in buffer_pacotes:
    if len(buffer_pacotes) == total_pacotes_esperados:
        # Buffer completo + pacote duplicado = ACK final pode ter perdido
        print("Reenviando ACK final")
        sock.sendto(pkt_ack, addr_cliente)
    continue  # Não armazena novamente
```

---

### 5️⃣ Dispatcher do Servidor: `handle_requisicao()` (servidor.py:336-378)

**Responsabilidade**: Executar em thread dedicada — isolar cada transferência

**Estratégia**:
```python
# Cada requisição ganha:
sock_worker = socket.socket()  # Socket próprio
# SO atribui porta efêmera automaticamente

# Executa GET ou POST
if tipo == TIPO_POST:
    receber_arquivo(sock_worker, ...)
elif tipo == TIPO_GET:
    enviar_arquivo(sock_worker, ...)
```

**Vantagem**:
- ✅ Dois clientes GET simultâneos não se interferem
- ✅ POST e GET podem ocorrer em paralelo
- ✅ Cada porta efêmera isola o tráfego

---

## 📋 Protocolo Definido

### Tipos de Mensagem

| ID | Nome | Sentido | Uso |
|:--:|------|---------|-----|
| 1 | POST | Cliente → Servidor | Requisição de upload |
| 2 | GET | Cliente → Servidor | Requisição de download |
| 3 | READY | Servidor → Cliente | Servidor pronto para receber (POST) |
| 4 | RESEND | Bidirecional | Solicita retransmissão (NACK) |
| 5 | ACK | Bidirecional | Confirmação de recebimento |
| 6 | ERROR | Servidor → Cliente | Mensagem de erro |
| 7 | HELLO | Servidor → Cliente | Handshake GET: "vou enviar" |
| 8 | HELLO-ACK | Cliente → Servidor | Handshake GET: "estou pronto" |

### Formato de Pacotes

#### **Pacote de Controle** (271 bytes)
```
Tipo (1B) | ID Arquivo (4B) | Tamanho Msg (2B) | Extensão (8B) | Mensagem (256B)
```

#### **Pacote de Dados** (1438 bytes)
```
ID (4B) | Sequência (4B) | Total (4B) | Tam Real (2B) | Extensão (8B) | 
Checksum MD5 (16B) | Payload (1400B)
```

---

## 🚀 Como Executar

### 1️⃣ Iniciar o Servidor

```bash
cd servidor
python servidor.py
```

**Saída Esperada**:
```
============================================================
  Servidor UDP — Transferência de Arquivos Confiável
  Porta: 12000  |  Diretório: ./servidor/
  Protocolo: segmentos 1400B | MD5 | Pipelining | Handshake
============================================================
Aguardando requisições...
```

### 2️⃣ Executar o Cliente

```bash
cd cliente
python cliente.py
```

**Menu Interativo**:
```
──────────────────────────────────────────────
 [1] POST — Enviar arquivo ao servidor
 [2] GET  — Baixar arquivo do servidor
 [0] Sair
──────────────────────────────────────────────
Escolha: 2
```

### 3️⃣ Exemplo de Execução: GET com Simulação

```
ID do arquivo: 1
Nome do arquivo: documento
Extensão: pdf

[SIM] Ativar simulação de perda de pacotes?
      [s] Sim  [N] Não: s
      
Modo:
  [1] Aleatório — descarta X% dos pacotes
  [2] Específico — informa números de sequência
Escolha: 2

Sequências a descartar: 2,5,8

[>] Enviando requisição GET...
[HANDSHAKE] HELLO recebido. Enviando HELLO-ACK...
[RX] Recebendo dados (ID=1)...
[SIM] Pacote #   2 descartado intencionalmente.
[SIM] Pacote #   5 descartado intencionalmente.
[SIM] Pacote #   8 descartado intencionalmente.
[TIMEOUT] Faltam 3 pacote(s). Solicitando retransmissão...
[SIM] Pacote #   2 liberado da lista de descarte para retransmissão.
[RESEND] Servidor pediu 3 pacote(s): [2, 5, 8]
[SIM] Relatório de simulação:
      Descartados: [2, 5, 8]
      Recuperados via RESEND: ✅
[✓] Arquivo montado e salvo: './cliente/documento.pdf'
```

---

## 🔍 Cenários Críticos Testáveis

### ✅ Teste 1: Simulação de Perda (GET)
```bash
1. Servidor: python servidor.py
2. Cliente: GET + [2] Específico + "1,3,5"
3. Resultado: Pacotes 1,3,5 descartados, recuperados via RESEND ✅
```

### ✅ Teste 2: Dois Clientes Simultâneos
```bash
Terminal 1: Servidor rodando
Terminal 2: Cliente GET (id=1)
Terminal 3: Cliente GET (id=2)  ← Simultâneo!
Resultado: Sem interferência ✅
```

### ✅ Teste 3: Arquivo Não Encontrado
```bash
1. Cliente: GET + "arquivo_inexistente"
2. Resultado: [❌ ERRO DO SERVIDOR] Arquivo não encontrado ✅
```

### ✅ Teste 4: Servidor Desliga Durante Transferência
```bash
1. Cliente: GET (arquivo grande)
2. Servidor: Ctrl+C durante transferência
3. Resultado: Múltiplos timeouts, depois "Servidor parou?" ✅
```

---

## 🛡️ Mecanismos de Confiabilidade

### 🔄 Recuperação de Perdas

1. **Detecção**: Timeout (2s) + Análise de sequência
2. **Solicitação**: RESEND seletivo (lista de sequências)
3. **Retransmissão**: Seletiva (se RESEND) ou completa (se timeout)
4. **Limite**: Máximo 5 tentativas antes de abortar

### ⚠️ Tratamento de Erros

1. **Arquivo não encontrado**: Mensagem ERROR descritiva
2. **Checksum inválido**: Descarta pacote, solicita RESEND
3. **Duplicatas**: Descarta payload, reenvia ACK (destravar)
4. **Timeout geral**: Tenta até 5 vezes

### 🔐 Integridade de Dados

- **Checksum**: MD5 por segmento (16 bytes)
- **Sequeção**: Número de sequência garante ordem
- **Completude**: Verifica se todos os pacotes chegaram

---

## 📊 Parâmetros de Configuração

```python
# TIMEOUTS
TIMEOUT_RX      = 2.0   # Receptor aguarda dados
TIMEOUT_TX      = 5.0   # Emissor aguarda ACK (cliente)
TIMEOUT_ACK     = 3.0   # Emissor aguarda ACK (servidor)
MAX_TENTATIVAS  = 5     # Limite de retransmissões

# SEGMENTAÇÃO
TAM_CHUNK       = 1400  # Bytes por datagrama
```

**Para ajustar**: Edite as constantes nos arquivos `.py`

---

## 📁 Estrutura de Diretórios

```
ProjetoRedes1/
├── README.md              ← Este arquivo
├── ANALISE.md            ← Análise detalhada de requisitos
├── cliente/
│   └── cliente.py        ← Implementação do cliente
├── servidor/
│   ├── servidor.py       ← Implementação do servidor
│   └── README.md         ← Especificação de requisitos originais
└── {arquivos_teste}/     ← Transferidos durante execução
```

---

## 🎓 Conceitos Aprendidos

✅ **Protocolo UDP**: Datagramas, sem conexão, sem confiabilidade  
✅ **Handshake robusto**: HELLO/HELLO-ACK e READY  
✅ **Pipelining**: Envio de múltiplos pacotes antes de confirmação  
✅ **Retransmissão seletiva**: NACK seletivo vs. completo  
✅ **Timeout duplo**: Emissor e receptor se protegem  
✅ **Checksum**: MD5 para detecção de corrupção  
✅ **Threading**: Múltiplos clientes sem bloqueio  
✅ **Portas efêmeras**: Isolamento de tráfego por cliente  

---

## 🐛 Troubleshooting

| Problema | Solução |
|----------|---------|
| `Address already in use` | Espere 30s ou mude a porta |
| Cliente conecta mas não recebe | Servidor pode estar travado em HELLO-ACK |
| Arquivo salvo vazio | Perda de 100% dos pacotes, tente novamente |
| Timeout contínuo | Aumentar TIMEOUT_RX/TX nas constantes |

---

## 📝 Notas Importantes

1. **MTU Ethernet**: 1500B - usamos 1438B para dados + 62B de overhead ✅
2. **Sem TCP**: Implementamos confiabilidade manualmente via timeout + RESEND
3. **Bidireção**: Mesmo socket UDP trata requisição + transferência
4. **Testes automatizados**: Veja `ANALISE.md` para cenários específicos

---

## ✨ Conclusão

Este projeto demonstra que **UDP pode ser confiável** quando implementamos adequadamente:
- Handshakes robustos
- Timeouts e retransmissões
- Verificação de integridade
- Controle de fluxo

Ideal para **ambientes com perda de pacotes**, simular falhas de rede ou aprender sobre protocolos de camada de aplicação.

---

**Autor**: Yago Constantino  
**Disciplina**: Redes de Computadores  
**Linguagem**: Python 3.8+  
**Protocolo**: UDP (porta 12000)
