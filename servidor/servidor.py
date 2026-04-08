from socket import *
from struct import *

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

