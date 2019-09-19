from voiplib.packet_flow import SocketController
from voiplib.config import *
from voiplib.opcodes import *
import struct
import time

s = SocketController()
s.connect(SERVER, CONTROL_PORT)
s.start()
s.do_tcp_client_auth()

time.sleep(1)
s.send_packet(SET_GATE, struct.pack('!4B4lH', 192, 168, 1, 138, 10000, -50, -60, -70, 6969))

while True:
    pkt = s.get_packet(True)
    print(pkt[2].opcode)
input('...')
