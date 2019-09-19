from socket import (
    socket, AF_INET, SOCK_STREAM, SOCK_DGRAM, SOL_SOCKET, SO_REUSEADDR,
)
import threading
import hashlib
import struct
import enum
import time

from Crypto.Util.Padding import pad, unpad
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5, AES
from Crypto.Hash import SHA
from Crypto import Random

from . import loggers
from .util.packets import Packet, PacketError
from .opcodes import *


class SocketMode(enum.IntEnum):
    TCP = 0
    UDP = 1


class HandshakeFailed(Exception):
    pass


class KeyManager:
    def __init__(self):
        self.registered = {}
        self._socks = {}

    @staticmethod
    def generate_client_id(key):
        # Converts any form of key into 16 bytes
        return hashlib.md5(key).digest()

    def get_aes(self, client_id):
        r = self.registered.get(client_id)
        if r is None:
            return None
        _, __, key, iv = r
        a = AES.new(key, AES.MODE_CBC, iv)
        return (a, a)

    def register(self, client_id, aes1, aes2, key, iv, sock):
        self.registered[client_id] = (aes1, aes2, key, iv)
        self._socks[client_id] = sock

    def sock_from_id(self, client_id):
        return self._socks.get(client_id)

    def id_from_sock(self, sock):
        for i in self._socks:
            if self._socks[i] == sock:
                return i
        return None

    def forget(self, client_id):
        if client_id in self._socks:
            del self._socks[client_id]
        if client_id in self.registered:
            del self.registered[client_id]


class SocketController:
    MAX_QUEUE = 10

    def __init__(self, mode=SocketMode.TCP, km=None):
        self.log = loggers.getLogger(__name__ + '.' + self.__class__.__name__)
        self._mode = mode

        self.km = km or KeyManager()

        # Create the socket(3) object
        if mode == SocketMode.TCP:
            self._sock = socket(AF_INET, SOCK_STREAM)
        else:
            self._sock = socket(AF_INET, SOCK_DGRAM)

        self._queue_lock = threading.Lock()
        self._queue_ready = threading.Event()
        self._pa_queue_lock = threading.Lock()
        self._pa_queue_ready = threading.Event()
        # NOTE: queue.Queue doesn't work here because of not beeing able to
        #       pop an item off based on a criteria.
        self._queue = []
        self._pa_queue = []

        # Server stuff
        self.server = False
        self.clients = []
        self._auth_clients = []

        self.client_ids = {}

        # Client stuff
        self.auth_done = False
        # self.aes = None
        self.send_address = None
        self.client_id = None

        if self.mode == SocketMode.TCP:
            self.log.info('Generating RSA key')
            self.key = RSA.generate(1024, Random.new().read)
            self.pub_key = self.key.publickey()
            self.log.info('Key gen finished')

        self.sequence = 0

    # Pass-through configuration
    def bind(self, host, port):
        self._sock.bind((host, port))

    def connect(self, host, port):
        if self.mode == SocketMode.TCP:
            self._sock.connect((host, port))
        else:
            self.send_address = (host, port)

    def listen(self, backlog):
        self.server = True
        self._sock.listen(backlog)

    def accept(self):
        return self._sock.accept()

    def close(self):
        self._sock.close()

    def getsockname(self):
        return self._sock.getsockname()

    def getnameinfo(self):
        return self._sock.getnameinfo()

    # Hooks
    def tcp_lost_hook(self, sock, addr):
        pass

    # Handlers
    def tcp_lost(self, sock, addr):
        if self.server:
            self.clients.remove((sock, addr))
            if sock in self._auth_clients:
                self._auth_clients.remove(sock)

            # if addr in self.client_aes:
            #     del self.client_aes[addr]
        self.log.info(f'Lost connection to {addr}')

        self.tcp_lost_hook(sock, addr)

    def send(self, data, to=None):
        if self.mode == SocketMode.TCP:
            if to is None:
                return self._sock.send(data)
            if not isinstance(to, socket):
                to = self.km.sock_from_id(to)
            return to.send(data)

        addr = to or self.send_address
        self._sock.sendto(data, addr)

    def start(self):
        # Make sure we don't accidentally hog a port
        self._sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)

        if self.server and self.mode == SocketMode.TCP:
            threading.Thread(
                target=self._accepter_loop,
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=self._handler_loop,
                args=(self._sock, None),
                daemon=True,
            ).start()

    def _accepter_loop(self):
        while True:
            conn, addr = self.accept()
            threading.Thread(
                target=self._handler_loop,
                args=(conn, addr),
                daemon=True,
            ).start()
            threading.Thread(
                target=self.do_tcp_server_auth,
                args=(conn, addr),
                daemon=True,
            ).start()
            self.clients.append((conn, addr))
            self.log.debug(f'Got clinet {addr}')

    def _handler_loop(self, sock, addr):
        while True:
            try:
                if self.mode == SocketMode.TCP:
                    packet = Packet.from_pipe(sock)
                else:
                    pdata, addr = sock.recvfrom(4096)
                    packet = Packet.from_bytes(pdata)
            except PacketError:
                # TODO: Proper handling here
                self.log.warn('Invalid packet encountered')
                continue
            except ConnectionResetError:
                self.tcp_lost(sock, addr)
                return

            # Un-apply any encryption scheme on this connection
            if self.client_id is None:
                aes = self.km.get_aes(packet.client_id)
            else:
                aes = self.km.get_aes(self.client_id)
            ppl = len(packet.payload)
            if aes is not None:
                try:
                    packet.payload = unpad(aes[1].decrypt(packet.payload), 16)
                except ValueError as e:
                    self.log.warn(f'Failed to decrypt AES: {e}')
                    continue

            self.log.debug('{0} bytes from {1} ({2} encrypted)'.format(len(packet.payload), addr, ppl))

            # Push the packet to the appropriate queue
            packet.source_addr = addr
            packet.source_sock = sock

            if self.auth_done or sock in self._auth_clients or self.mode == SocketMode.UDP:
                with self._queue_lock:
                    self._queue.append((sock, addr, packet))
                    self._queue_ready.set()
                    while len(self._queue) > self.MAX_QUEUE:
                        self.log.error('Queue to large!')
                        self._queue.pop(0)
            else:
                with self._pa_queue_lock:
                    self._pa_queue.append((sock, addr, packet))
                    self._pa_queue_ready.set()

    def get_packet(self, blocking=False, check=None, in_auth=False):
        # The queue for pre-auth sockets is different from post-auth
        queue = self._queue if not in_auth else self._pa_queue
        q_ready = self._queue_ready if not in_auth else self._pa_queue_ready
        q_lock = self._queue_lock if not in_auth else self._pa_queue_lock

        if blocking:
            n = 0
            while True:
                # Wait for an item on the queue
                q_ready.wait()
                with q_lock:
                    # If the packet fails the custom check...
                    try:
                        if check is not None and not check(queue[n]):
                            # ...ignore it
                            n += 1
                            q_ready.clear()
                            continue
                    except IndexError:
                        continue

                    # Reset the queue_ready flag to the correct value
                    if len(queue) == 1:
                        q_ready.clear()
                    else:
                        q_ready.set()
                    return queue.pop(n)

        with q_lock:
            if queue:
                # Find the first item on the queue matching the check
                for n, i in enumerate(queue):
                    if check is None or check(i):
                        if len(queue) == 1:
                            # Queue is empty, unset the flag.
                            q_ready.clear()
                        return queue.pop(n)
            return None

    def send_packet(self, opcode, payload, sequence=None, to=None, client_id=None, origin=None):
        if sequence is None:
            sequence = self.sequence
            self.sequence += 1
            self.sequence %= 0xff_ff
        ts = int(time.time())

        # If we're using an encryption scheme for this connection, apply it
        if self.client_id is not None:
            payload = self.km.get_aes(self.client_id)[0].encrypt(pad(payload, 16))
        elif client_id is not None:
            aes = self.km.get_aes(client_id)[0]
            payload = aes.encrypt(pad(payload, 16))

        origin = self.client_id or origin

        # Construct and send the packet
        packet = Packet.make_bytes(opcode, payload, ts, self.sequence, origin)
        self.send(packet, to=to)

    def do_tcp_client_auth(self):
        if self.mode != SocketMode.TCP:
            self.log.error('!! REFUSING TO DO HANDSHAKE OUTSIDE OF TCP !!')
            return

        self.log.info('Starting client-server authentication')

        def assert_op(packet, opcode):
            if packet[2].opcode != opcode:
                self.send_packet(ABRT, b'')
                self.close()
                raise HandshakeFailed

        # Request authentication
        self.send_packet(HELLO, b'')
        resp = self.get_packet(True, in_auth=True)
        assert_op(resp, ACK)

        # Send our public key
        self.send_packet(RSA_KEY, self.pub_key.exportKey('DER'))

        # Get the AES parameters
        resp = self.get_packet(True, in_auth=True)
        assert_op(resp, AES_KEY)

        # Build and RSA cipher, then an AES one
        cipher = PKCS1_v1_5.new(self.key)
        sentinel = Random.new().read(15 + SHA.digest_size)
        aes_key = cipher.decrypt(resp[2].payload, sentinel)


        key, iv = aes_key[:16], aes_key[32:]
        nonce = aes_key[16:32]
        aes = AES.new(key, AES.MODE_CBC, iv)
        aes2 = AES.new(key, AES.MODE_CBC, iv)

        # Return the encrypted nonce
        encr = aes.encrypt(nonce)
        self.send_packet(AES_CHECK, encr)

        # self.aes = (aes, aes2)
        self.km.register(nonce, aes, aes2, key, iv, self._sock)

        resp = self.get_packet(True, in_auth=True)
        assert_op(resp, ACK)

        self.log.info('Client-server handshake complete')

        self.auth_done = True

        self.client_id = nonce
        return nonce

    def do_tcp_server_auth(self, sock, addr):
        if self.mode != SocketMode.TCP:
            self.log.error('!! REFUSING TO DO HANDSHAKE OUTSIDE OF TCP !!')
            return

        self.log.debug('Starting server-client authentication')

        def check(packet):
            return packet[0] == sock

        def assert_op(packet, opcode):
            if packet[2].opcode != opcode:
                self.send_packet(ABRT, b'', to=sock)
                sock.close()
                raise HandshakeFailed

        # Get initial HELLO
        hello = self.get_packet(True, check=check, in_auth=True)
        assert_op(hello, HELLO)
        # ACK it
        self.send_packet(ACK, b'', to=sock)

        # Get the client's RSA key
        key = self.get_packet(True, check=check, in_auth=True)
        assert_op(key, RSA_KEY)
        client_key = RSA.importKey(key[2].payload)

        # Construct a new AES 256 cipher
        key = Random.get_random_bytes(16)
        iv = Random.new().read(AES.block_size)
        aes = AES.new(key, AES.MODE_CBC, iv)
        aes2 = AES.new(key, AES.MODE_CBC, iv)
        nonce = KeyManager.generate_client_id(key)

        # Encrypt the AES parameters using RSA
        cipher = PKCS1_v1_5.new(client_key)
        resp = cipher.encrypt(key + nonce + iv)

        # Send the params to the client
        self.send_packet(AES_KEY, resp, to=sock)

        # Get the nonce-based AES check
        nonce_resp = self.get_packet(True, check=check, in_auth=True)
        assert_op(nonce_resp, AES_CHECK)

        nonce_resp = aes2.decrypt(nonce_resp[2].payload)
        if nonce_resp != nonce:
            self.send_packet(ABRT, b'', to=sock)
            sock.close()
            raise HandshakeFailed

        self.log.debug('Server-client handshake complete')

        # Register the client
        self.km.register(nonce, aes, aes2, key, iv, sock)

        self._auth_clients.append(sock)

        # Send the final ACK to finish the handshake
        self.send_packet(ACK, b'', to=nonce)

    @property
    def mode(self):
        return self._mode
