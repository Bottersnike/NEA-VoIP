import hashlib

from Crypto.Cipher import AES


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
        return a, a

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
