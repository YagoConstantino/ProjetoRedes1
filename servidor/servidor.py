from socket import *
from struct import *
from os import *

# Formato do pacote:
# !II?H1400s = 4+4+1+2+1400 = 1411 bytes por pacote
# MTU de 1500 bytes
FORMAT = "!II?H1400s"
PACKEGE_SIZE = 1400

serverSocket = socket(AF_INET,SOCK_DGRAM)

serverSocket.bind(('',12000))
print("Servidor aberto para receber pacotes....\n")

while True:
    msg,addr = serverSocket.recvfrom(2048)

    print("MSG: ",msg," Endereço: ",addr,"\n")
    mod_msg = msg.decode().upper()
    
    serverSocket.sendto(mod_msg.encode(),addr)
    if(msg.decode() == "fecha"): break

serverSocket.close()

