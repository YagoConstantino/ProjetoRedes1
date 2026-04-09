from socket import *
import struct

server = ('127.0.0.1',12000)
clientSocket = socket(AF_INET,SOCK_DGRAM)

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
dicionarioGlobal = {}

while (True):
    msg = input("Escreva uma mensagem ou 'fecha': ")
    
    if msg == "fecha": 
        break
        
    extensao = input("Escolha uma extensao (txt, png, etc): ")
    tipo = int(input("Escolha uma função (POST = 1 /// GET = 2): "))
    idArquivo = int(input("Id do arquivo: "))
    
    extensaoBytes = extensao.encode('utf-8').ljust(8, b'\x00')
    msgBytes = msg.encode('utf-8')
    tamRealMsg = len(msgBytes)
    
    msgCompletada = msgBytes[:256].ljust(256, b'\x00')
    
    pacote = struct.pack(FORMAT2, tipo, idArquivo, tamRealMsg, extensaoBytes, msgCompletada)
    clientSocket.sendto(pacote, server)
    
    # Aguarda resposta (pode ser arquivo ou erro)
    while (True):
        resp, addr = clientSocket.recvfrom(2048)
        
        # Se for mensagem pequena, é erro 
        if len(resp) < 1419:
            print(f"Resposta servidor: {resp.decode()}")
            break
        
        # Se for pacote grande, desempacota como arquivo
        idArquivo, cont, ehUltimo, tamReal, tipo, dadosCompletos = struct.unpack(FORMAT, resp)
        extensaoLimpa = tipo.decode('utf-8').strip('\x00')    
        
        if idArquivo not in dicionarioGlobal:
            dicionarioGlobal[idArquivo] = {}
            
        dicionarioGlobal[idArquivo][cont] = dadosCompletos[:tamReal]
        print(f"Recebi pacote {cont}/{cont if ehUltimo else '?'} - Tipo: {extensaoLimpa}")
        
        if ehUltimo:
            nomeFinal = f"{msg}.{extensaoLimpa}"
            with open("cliente/"+nomeFinal, "wb") as f:
                for s in sorted(dicionarioGlobal[idArquivo].keys()):
                    f.write(dicionarioGlobal[idArquivo][s])
            
            print(f"✓ Arquivo '{nomeFinal}' salvo com sucesso!")
            del dicionarioGlobal[idArquivo]
            break
            
    if msg == "fecha": break

clientSocket.close()


