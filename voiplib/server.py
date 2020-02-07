import threading
import struct
import time
from socket import socket

from .socket_controller import SocketController, SocketMode, KeyManager
from .state_manager import StateManager
from .recorder import Recorder
from .opcodes import *
from .config import *
from . import loggers
from . import history


from .database.orm import DB, Primary
from .database import Devices, GateConfig, CompConfig


class Server:
    def __init__(self) -> None:
        """
        Create a new server instance.
        """
        loggers.createFileLogger(__name__)

        self.log = loggers.getLogger(__name__ + '.' + self.__class__.__name__)

        # Create our local key manager
        self.km = KeyManager()

        # Create the 4 sockets the server will need to operate
        self.sock = SocketController(km=self.km)
        self.cont_sock = SocketController()
        self.udp_recv = SocketController(SocketMode.UDP, km=self.km)
        self.udp_send = SocketController(SocketMode.UDP, km=self.km)

        # Setup a state manager and bind it to the sockets
        self.sm = StateManager(self.sock, self.cont_sock, self.km)
        # Setup a recorder
        self.recorder = Recorder()

        # Bind all the sockets to their respective hosts and ports
        self.udp_recv.bind('', TCP_PORT)
        self.udp_recv.start()

        self.sock.bind(HOST, TCP_PORT)
        self.sock.listen(10)

        self.cont_sock.bind(HOST, CONTROL_PORT)
        self.cont_sock.listen(10)
        self.cont_udp_port = None

        self.sock.start()
        self.cont_sock.start()

        self.udp_lock = threading.Lock()
        self.udp_listeners = {}

        # Bind event hooks to the controller
        self.sock.tcp_lost_hook = self.tcp_lost
        self.sock.new_tcp_hook = self.new_tcp

    def tcp_lost(self, sock: socket, _) -> None:
        """
        A handler that is bound to a socket controller, called when a TCP
        client disconnects. This function grabs the udp mutex, then clears out
        any now-unneeded state for that client.
        """
        with self.udp_lock:
            client_id = self.km.id_from_sock(sock)
            if not client_id:
                # Not sure who this socket was, ignore them.
                return

            if client_id in self.udp_listeners:
                del self.udp_listeners[client_id]
            self.km.forget(client_id)

            # Log the event
            target_device = Devices.select(deviceID=client_id.decode('latin-1'))
            if target_device:
                history.insert(target_device, history.EVENT_DCON)

            # Inform the control surface a client has left.
            self.cont_sock.send_packet(CLIENT_LEAVE, client_id)

    def new_tcp(self, sock: socket, addr, client_id: bytes) -> None:
        """
        A hook bound to socket controllers, called when a client completes
        their handshake. This function is responsible for saving and loading
        data from the database to retain state between sessions.
        """
        # TODO: This!
        #       This should be based off the pubkey.
        target_device = Devices.select(deviceID=client_id.decode('latin-1'))

        if not target_device:
            self.log.debug('Device not found in database.')
            # Create the audio config pair
            gate = GateConfig(*self.sm.gates[client_id])
            comp = CompConfig(*self.sm.compressors[client_id])
            # Insert them so they get identifiers
            GateConfig.insert(gate)
            CompConfig.insert(comp)

            # Create the core device config
            target_device = Devices(
                client_id.decode('latin-1'), "", addr[0],
                self.sm.names[client_id],
                False, gate, comp
            )

            # Register the device to the database
            Devices.insert(target_device)
        else:
            self.log.debug('Restoring device config from database.')
            # Restore all the configuation from the located device
            dev = target_device[0]
            self.sm.set_name(client_id, dev.name)

            self.sm.set_gate(
                client_id, (dev.gate.attack, dev.gate.hold,
                            dev.gate.release, dev.gate.threshold)
            )
            self.sm.set_compressor(
                client_id, (dev.gate.attack, dev.gate.release,
                            dev.gate.threshold)
            )
        
        # Log the event
        history.insert(target_device, history.EVENT_CONN)
        
    def udp_mainloop(self):
        """
        The mainloop for UDP sections of the server. This handles mainly
        routing of audio between mutliple clients.
        """
        while True:
            pkt = self.udp_recv.get_packet(True)
            self.log.debug(f'UDP packet from {pkt[1]}: {pkt[2].opcode}')
            if pkt[2].opcode == AUDIO:
                # Try feed the packet to the recorder. This may fail if there
                # is a disk IO failure, or if the audio payload is malformed.
                try:
                    self.recorder.feed(pkt[2].client_id, pkt[2].payload)
                except Exception as e:
                    self.log.warning(f'Failed to record audio for {pkt[2].client_id}: {e}')

                # Grab the UDP mutex for a short period
                with self.udp_lock:
                    listeners = dict(self.udp_listeners)
                    # Locate all the clients in the same room
                    can_listen = set(sum([i for i in self.sm.rooms
                                          if pkt[2].client_id in i], []))
                    # If a control surface is attached, forward the packet
                    # there, too.
                    if self.cont_udp_port is not None:
                        can_listen.add(self.cont_udp_port)

                    # Retransmit the audio to all clients allowed to listen.
                    for i in can_listen:
                        if pkt[2].client_id != i and i in listeners:
                            self.udp_send.send_packet(
                                AUDIO, pkt[2].payload, to=listeners[i],
                                client_id=i, origin=pkt[2].client_id)

    def cont_mainloop(self):
        """
        The mainloop responsible for interactions with the control surface.
        """
        while True:
            pkt = self.cont_sock.get_packet(True)

            self.log.debug(f'CONT packet from {pkt[1]}: {pkt[2].opcode}')
            if pkt[2].opcode == SET_GATE:
                try:
                    # Decode the parameters from the payload
                    client_id = pkt[2].payload[:16]
                    attack, hold, release, threshold, nonce = (
                        struct.unpack('!4lH', pkt[2].payload[16:])
                    )
                    attack = max(0, min(65535, attack))
                    hold = max(0, min(65535, hold))
                    release = max(0, min(65535, release))
                    threshold = max(0, min(65535, threshold))

                    # Locate the targeted client
                    sock = self.km.sock_from_id(client_id)
                    if sock is not None:
                        # Inform the client of the change
                        self.sock.send_packet(
                            SET_GATE,
                            pkt[2].payload[16:],
                            to=sock,
                            client_id=client_id
                        )
                        # Update the state manager
                        self.sm.set_gate(
                            client_id, (attack, hold, release, threshold)
                        )
                    # Inform the control surface of the success state
                    self.cont_sock.send_packet(
                        SET_FAIL if sock is None else SET_ACK,
                        struct.pack('!H', nonce), to=pkt[0])
                except struct.error:
                    self.log.warning('Failed to decode CONT packet')
            elif pkt[2].opcode == SET_COMP:
                try:
                    # Dedcode the parameters from the payload
                    client_id = pkt[2].payload[:16]
                    attack, release, threshold, nonce = (
                        struct.unpack('!3lH', pkt[2].payload[16:])
                    )
                    attack = max(0, min(65535, attack))
                    release = max(0, min(65535, release))
                    threshold = max(0, min(65535, threshold))

                    # Locate the targeted client
                    sock = self.km.sock_from_id(client_id)
                    if sock is not None:
                        # Inform the client of the changes
                        self.sock.send_packet(
                            SET_COMP,
                            pkt[2].payload[16:],
                            to=sock,
                            client_id=client_id
                        )
                        # Update the state manager
                        self.sm.set_compressor(
                            client_id,
                            (attack, release, threshold)
                        )
                    # Inform the control surface of the success state
                    self.cont_sock.send_packet(
                        SET_FAIL if sock is None else SET_ACK,
                        struct.pack('!H', nonce), to=pkt[0])
                except struct.error:
                    self.log.warning('Failed to decode CONT packet')
            elif pkt[2].opcode == SET_NAME:
                # Extract the name from the payload
                client_id = pkt[2].payload[:16]
                # Update the state manager
                self.sm.set_name(
                    client_id, pkt[2].payload[16:271].decode('latin-1')
                )
            elif pkt[2].opcode == SET_ROOMS:
                # Decode the list from the payload
                client_id = pkt[2].payload[:16]
                room_n = pkt[2].payload[16]
                rooms = pkt[2].payload[17: 17 + room_n]
                # Update the state manager
                self.sm.set_rooms(client_id, rooms)

                # Log the event
                target_device = Devices.select(deviceID=client_id.decode('latin-1'))
                if target_device:
                    history.insert(target_device, history.EVENT_TEXT, 'Moved rooms')
            elif pkt[2].opcode == START_RECORD:
                # Decode the payload
                client_id = pkt[2].payload[:16]
                self.recorder.recording.add(client_id)
                self.recorder.rec_start[client_id] = time.time()

                # Log the event
                target_device = Devices.select(deviceID=client_id.decode('latin-1'))
                if target_device:
                    history.insert(target_device, history.EVENT_TEXT, 'Recording started')
            elif pkt[2].opcode == STOP_RECORD:
                # Decode the payload
                client_id = pkt[2].payload[:16]
                if client_id in self.recorder.recording:
                    # Stop recording the client
                    self.recorder.recording.remove(client_id)
                    if client_id in self.recorder.recordings:
                        # Write any remaining buffer to disk
                        self.recorder.recordings[client_id].flush()
                        self.recorder.recordings[client_id].finish()
                        # Clean up after the recorder
                        del self.recorder.recordings[client_id]
                        del self.recorder._decoders[client_id]
                        del self.recorder._counts[client_id]
                
                # Log the event
                target_device = Devices.select(deviceID=client_id.decode('latin-1'))
                if target_device:
                    history.insert(target_device, history.EVENT_TEXT, 'Recording stopped')
            elif pkt[2].opcode == GET_RECORD:
                # Decode the payload
                client_id = pkt[2].payload[:16]
                if client_id not in self.recorder.recording:
                    # Send a dummy message
                    self.cont_sock.send_packet(GET_RECORD, b'Not recording', to=pkt[0])
                else:
                    # Convert seconds into a nicer format
                    rec_len = time.time() - self.recorder.rec_start.get(client_id, time.time())
                    ms = int(round(rec_len % 1, 3) * 1000)
                    mi, se = divmod(int(rec_len), 60)
                    hr, mi = divmod(mi, 60)
                    dur = f'{hr:02}:{mi:02}:{se:02}.{ms:0<3}'.encode()
                    # Respond to the client
                    self.cont_sock.send_packet(GET_RECORD, b'Recording.. ' + dur, to=pkt[0])
            elif pkt[2].opcode == REGISTER_UDP:
                # Register the UDP recieve port for the control surface.
                try:
                    self.cont_udp_port = struct.unpack('!H', pkt[2].payload)[0]
                except struct.error:
                    self.log.warning(
                        'Invalid packet when registering UDP port'
                    )

    def mainloop(self):
        """
        The mainloop for client TCP sockets. This is largely responsible for
        register UDP connections, as encryption is handler by socket
        controllers.
        """
        threading.Thread(target=self.udp_mainloop, daemon=True).start()
        threading.Thread(target=self.cont_mainloop, daemon=True).start()

        while True:
            pkt = self.sock.get_packet(True)

            self.log.debug(f'TCP packet from {pkt[1]}: {pkt[2].opcode}')
            if pkt[2].opcode == REGISTER_UDP:
                # Attempt to decode the packet
                try:
                    udp_port = struct.unpack('!H', pkt[2].payload)[0]

                    self.udp_listeners[pkt[2].client_id] = (
                        pkt[1][0],  # Source IP
                        udp_port
                    )
                except struct.error:
                    self.log.warning(
                        'Invalid packet when registering UDP port'
                    )


if __name__ == '__main__':
    Server().mainloop()
