import hashlib
from typing import Tuple, Optional, TypeVar
from socket import socket

from Crypto.Cipher import AES

from .database import Devices


AESt = TypeVar('AES')


class KeyManager:
    def __init__(self) -> None:
        self.registered = {}
        self._socks = {}

    @staticmethod
    def generate_client_id(key: bytes, address: Tuple[str, int]) -> bytes:
        """
        Generate or retreive the client id to assign or that was previously
        assigned for a given client. The key is used in the absense of an
        existing client id in order to generate the new id to issue.

        :param bytes key: The key to use when generating a new io
        :param typle address: The address of the connecting client
        """
        # Check the database for a previously assigned id
        dev = Devices.select(lastIp=address[0])
        # TODO: Make this use pubkeys
        if False or dev:
            return dev[0].deviceID
        
        # Converts any form of key into 16 bytes
        return hashlib.md5(key).digest()

    def get_aes(self, client_id: bytes) -> Optional[Tuple[AESt, AESt]]:
        """
        Return the pair of encoder and decoder required to perform the AES
        encryption for any given client, identified by their client id.

        :param bytes client_id: The client id to lookup
        """
        # Search for the requested client
        r = self.registered.get(client_id)
        if r is None:
            return None
        # Flatten the located metadata
        _, __, key, iv = r
        a = AES.new(key, AES.MODE_CBC, iv)
        # As in, both the decoder and encoder are currently able to function
        # off a single instance of the AES function. In some cases this is not
        # possible, and as such this function returns both an object to be used
        # for encoding, and a second to be used for decoding.
        # In this implementation, the same object is returned twice. This is by
        # design.
        return a, a

    def register(self, client_id: bytes, aes1: AES, aes2: AES, key: bytes,
                 iv: bytes, sock: socket) -> None:
        """
        Register a new client to the key manager.

        :param bytes client_id: The id of the new client
        :param AES aes1: The primary AES instance
        :param AES aes2: The secondary AES instance
        :param bytes key: The key used to create further AES instances
        :param bytes iv: The initialisation vector for the AES algorithm
        :param socket sock: The socket this client is utilising currently
        """
        self.registered[client_id] = (aes1, aes2, key, iv)
        self._socks[client_id] = sock

    def sock_from_id(self, client_id: bytes) -> Optional[socket]:
        """
        Locate the socket required to transmit data to a given client

        :param bytes client_id: The client to lookup
        """
        return self._socks.get(client_id)

    def id_from_sock(self, sock: socket) -> Optional[bytes]:
        """
        Attempt to locate the client id for a given socket.
        This is functionally the inverse of :func:`register`.

        :param socket sock: The socket to lookup
        """
        for i in self._socks:
            if self._socks[i] == sock:
                return i

        # No matching clients could be found
        return None

    def forget(self, client_id: bytes) -> None:
        """
        Expunge a client from the local tracking state.

        :param bytes client_id: The client to remove
        """
        # Make sure to not remove something that doesn't exist
        if client_id in self._socks:
            del self._socks[client_id]
        if client_id in self.registered:
            del self.registered[client_id]
