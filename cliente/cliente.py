from socket import *
from struct import * 

server = ('127.0.0.10',12000)

clientSocket = socket(AF_INET,SOCK_DGRAM)

while (True):
    msg = input("Escreva uma mensagem:  ")

   
    clientSocket.sendto(msg.encode(),server)
    
    resp,addr = clientSocket.recvfrom(2048)
    if(msg == "fecha"): break
    print("Servidor: ",addr," Resposta: ",resp.decode())

clientSocket.close()


