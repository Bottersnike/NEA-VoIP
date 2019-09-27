# Generic
ACK = 0
ABRT = 1

# Handshaking
HELLO = 2
RSA_KEY = 3
AES_KEY = 4
AES_CHECK = 5

# Main protocol
AUDIO = 10
REGISTER_UDP = 11

SET_GATE = 12
SET_COMP = 13
SET_ACK = 14
SET_FAIL = 15
CLIENT_JOIN = 16
CLIENT_LEAVE = 17
SET_NAME = 18
SET_ROOMS = 19

"""
Handshake packet flow is:
    HELLO ->
    -> ACK
    RSA_KEY ->
    -> AES_KEY
    AES_CHECK ->
    -> ACK
"""
