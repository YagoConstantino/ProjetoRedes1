from socket import *
from struct import * 
from os import * 

server = ('127.0.0.10',12000)

clientSocket = socket(AF_INET,SOCK_DGRAM)

# Formato do pacote:
# !II?H1400s = 4+4+1+2+1400 = 1411 bytes por pacote
# Seguro: bem abaixo do MTU de 1500 bytes
FORMAT = "!II?H1400s"
PACKEGE_SIZE = 1400


while (True):
    msg = input("Escreva uma mensagem:  ")

   
    clientSocket.sendto(msg.encode(),server)
    
    resp,addr = clientSocket.recvfrom(2048)
    if(msg == "fecha"): break
    print("Servidor: ",addr," Resposta: ",resp.decode())

clientSocket.close()


