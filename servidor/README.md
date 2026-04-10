# 🚀 Projeto: Transferência de Arquivos Confiável sobre UDP

## 🎯 Objetivo do Projeto
Desenvolver uma aplicação cliente-servidor para transferência de arquivos utilizando o protocolo UDP. O foco principal é a implementação de mecanismos básicos de controle e confiabilidade diretamente sobre UDP, simulando funcionalidades que o TCP oferece nativamente.

---

## 🛠️ 1. Requisitos Gerais
* **Linguagem de Programação:** A escolha da linguagem é livre (ex: Python, Java, C/C++, etc.).
* **Restrição de Bibliotecas:** **Não é permitido** o uso de bibliotecas de alto nível que abstraiam a manipulação direta do protocolo UDP. A implementação deve utilizar a API de sockets do sistema operacional (ou da linguagem escolhida) para criar, enviar e receber datagramas UDP.
* **Sugestão (Opcional):** Recomenda-se iniciar com um exemplo simples “Hello World” cliente/servidor UDP para familiarização com a API de sockets antes de abordar a transferência de arquivos.

---

## 🖥️ 2. Requisitos do Servidor UDP

### 2.1. Inicialização e Configuração
* **Ordem de Execução:** O servidor deve ser executado antes do cliente.
* **Porta:** Deve operar em uma porta UDP especificada, com número maior que 1024 (portas abaixo de 1024 geralmente exigem privilégios de administrador).

### 2.2. Recepção e Protocolo
* Aguardar conexões/mensagens de clientes.
* Interpretar as requisições recebidas. É necessário definir e implementar um protocolo de aplicação simples sobre UDP para que o cliente requisite arquivos.
  * *Exemplo de formato de requisição:* `GET /nome_do_arquivo.ext`

### 2.3. Processamento da Requisição
* Verificar se o arquivo solicitado existe.
* **Se o arquivo não existir:** Enviar uma mensagem de erro claramente definida pelo seu protocolo para o cliente.

### 2.4. Transmissão do Arquivo (se existir)
* O arquivo a ser transmitido deve ser relativamente grande (ex: `> 1 MB`) para justificar a segmentação.
* **Segmentação:** Dividir o arquivo em múltiplos segmentos/pedaços para envio em datagramas UDP.
* **Cabeçalho Customizado:** Cada segmento enviado deve conter informações de controle definidas pelo seu protocolo (ver a seção *Considerações de Protocolo* abaixo).
* **Retransmissão:** Implementar lógica para reenviar segmentos específicos caso o cliente solicite (devido a perdas ou erros).

---

## 💻 3. Requisitos do Cliente UDP

### 3.1. Inicialização e Conexão
* **Ordem de Execução:** O cliente deve ser executado após o servidor estar ativo.
* **Conexão:** Permitir que o usuário especifique o endereço IP e a porta do servidor UDP ao qual deseja se conectar.

### 3.2. Requisição
* Enviar uma requisição ao servidor, utilizando o protocolo de aplicação definido, para solicitar um arquivo específico.
  * *Exemplo de entrada do usuário:* `@IP_Servidor:Porta_Servidor/nome_do_arquivo.ext`

### 3.3. Simulação de Perda (Crucial)
* Implementar uma opção (ex: via entrada do usuário ou configuração) que permita ao cliente **descartar intencionalmente** alguns segmentos recebidos do servidor.
* Isso é crucial para testar o mecanismo de recuperação de dados. 
* A interface deve informar quais segmentos (ex: por número de sequência) estão sendo descartados.

### 3.4. Recepção e Montagem
* Receber os segmentos do arquivo enviados pelo servidor.
* Armazenar e ordenar os segmentos recebidos corretamente.
* Verificar a integridade de cada segmento (ex: usando checksum ou resumos criptográficos como o MD5 e SHA).

### 3.5. Verificação e Finalização
Após receber todos os segmentos esperados (ou um sinal de fim de transmissão do servidor), verificar a integridade e completude do arquivo:
* **Se o arquivo estiver OK:** Salvar o arquivo reconstruído localmente e informar o sucesso ao usuário. Opcionalmente, apresentar/abrir o arquivo.
* **Se o arquivo estiver com erro ou incompleto:**
  1. Identificar quais segmentos estão faltando ou corrompidos.
  2. Solicitar a retransmissão desses segmentos específicos ao servidor, utilizando o protocolo definido.
  3. Repetir o processo de recepção e verificação até que o arquivo esteja completo e correto.
* **Interpretação de Erros:** Interpretar e exibir mensagens de erro recebidas do servidor (ex: “Arquivo não encontrado”).

---

## 📐 4. Considerações Obrigatórias para o Design do Protocolo

O aluno deve projetar e justificar as escolhas para os seguintes aspectos do protocolo de aplicação sobre UDP:

### 📦 4.1. Segmentação e Tamanho do Buffer
* Como o arquivo será dividido? Qual o tamanho máximo de dados por datagrama UDP (payload)?
* Este tamanho deve ser fixo ou variável? Como ele se relaciona com o **MTU (Maximum Transmission Unit)** da rede? *(Necessário pesquisar sobre MTU e fragmentação IP)*.
* Os buffers de envio (servidor) e recepção (cliente) precisam ter tamanhos relacionados?

### 🛡️ 4.2. Detecção de Erros
* Como a integridade dos dados em cada segmento será verificada?
* É necessário implementar um checksum?
* Qual algoritmo usar? (Ex: CRC32, soma simples).

### 🔢 4.3. Ordenação e Detecção de Perda
* Como o cliente saberá a ordem correta dos segmentos? É necessário um número de sequência?
* Como o cliente detectará que um segmento foi perdido (e não apenas atrasado)?

### 🚦 4.4. Controle de Fluxo/Janela (Opcional Avançado)
* Considerar como evitar que o servidor envie dados mais rápido do que o cliente consegue processar (embora um controle de fluxo completo seja complexo e possa estar fora do escopo inicial).

### ✉️ 4.5. Mensagens de Controle
Definir claramente os formatos das mensagens de:
* Requisição de arquivo.
* Envio de segmento de dados (incluindo cabeçalhos com número de sequência, checksum, etc.).
* Confirmação de recebimento (se houver - ACK).
* Solicitação de retransmissão (NACK).
* Mensagens de erro.