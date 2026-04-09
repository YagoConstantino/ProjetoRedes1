from socket import *
import struct
import os

# Formato do pacote:
# !II?H8s1400s = 4+4+1+2+8+1400 = 1419 bytes por pacote
# !     -> Network order (Big-Endian)
# I     -> ID do Arquivo (4 bytes)
# I     -> Número do Pacote (4 bytes)
# ?     -> Flag: É o último pacote? (1 byte)
# H     -> Tamanho útil dos dados neste pacote (2 bytes)
# 8s    -> Extensão do arquivo (8 bytes para o tipo: txt, png, etc)
# 1400s -> Dados do arquivo (1400 bytes)
FORMAT = "!II?H8s1400s"
PACKGE_SIZE = 1400

#!: Network Order
#B: Tipo da mensagem (1 byte).
#I: ID do Arquivo (4 bytes).
#H: Tamanho real da mensagem (2 bytes).
#8s: Extensão (8 bytes) - <-- O campo novo aqui!
#256s: A mensagem de texto (256 bytes).
#Total: 1 + 4 + 2 + 8 + 256 = 271 bytes.
FORMAT2 = "!BIH8s256s"


serverSocket = socket(AF_INET,SOCK_DGRAM)
serverSocket.bind(('',12000))
print("Servidor aberto para receber pacotes....\n")

def enviarArquivo(nomeArquivo, tipo, addr, idArquivo):
   #Converter tipo (bytes) para string e remover null bytes
    extensao = tipo.decode('utf-8').strip('\x00')
    nomeReal = nomeArquivo + "." + extensao
    
    if not os.path.exists(nomeReal):
        serverSocket.sendto(b"Erro: Arquivo nao encontrado", addr)
        return
    
    totalBytes = os.path.getsize(nomeReal)
    
    if totalBytes == 0:
        serverSocket.sendto(b"Erro: Arquivo vazio", addr)
        return

    with open(nomeReal,"rb") as file:
        cont = 0
        while(True):
            bytesLidos = file.read(PACKGE_SIZE)
            if not (bytesLidos): break
            
            cont+=1
            ehUltimo = file.tell() >= totalBytes
            tamReal = len(bytesLidos)
            
            if(tamReal < PACKGE_SIZE):
                dadosCompletos = bytesLidos.ljust(PACKGE_SIZE, b'\x00')
            else:
                dadosCompletos = bytesLidos
            
            tipo_bytes = extensao.encode().ljust(8, b'\x00')

            pacote = struct.pack(FORMAT, idArquivo, cont, ehUltimo, tamReal, tipo_bytes, dadosCompletos)
            
            serverSocket.sendto(pacote, addr)
            print(f"Enviado pacote {cont} | Útil: {tamReal} bytes")
            
while True:
    pacote,addr  = serverSocket.recvfrom(2048)
    tipo, idArquivo, tamRealMsg, extensaoBytes, msg= struct.unpack(FORMAT2,pacote)
    print("MSG: ", msg, " Endereço: ", addr, "\n")
    
    # Tenta enviar o arquivo PRIMEIRO
    nomeArquivo = msg.decode().strip('\x00')
    enviarArquivo(nomeArquivo, extensaoBytes, addr, idArquivo)
    
    if(msg.decode() == "fecha"): 
        break

serverSocket.close()


