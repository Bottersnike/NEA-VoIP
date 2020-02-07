import struct
import threading
import traceback

from .socket_controller import SocketController, SocketMode, KeyManager
from .audio_processors import Gate, Compressor, NullSink, TransmitAudio
from .audioio import AudioIO
from .opcodes import AUDIO, REGISTER_UDP, SET_GATE, SET_COMP
from .config import TCP_PORT, SERVER
from . import loggers


class Client:
    def __init__(self, no_input: bool=False, no_output: bool=False):
        # Create a logging instance
        self.log = loggers.getLogger(__name__ + '.' + self.__class__.__name__)

        # Setup kill timers to abort the client
        self._alive = True
        self.kill_me_now = threading.Event()

        # Prepare for the state provided by the server
        self.client_id = None
        self.km = KeyManager()

        # Setup the socket used for TCP communication
        self.sock = SocketController(km=self.km)
        self.sock.connect(SERVER, TCP_PORT)
        self.sock.start()
        self.sock.tcp_lost_hook = self.kill

        # Setup the UDP socket pair for audio data
        self.udp_send = SocketController(SocketMode.UDP, km=self.km)
        self.udp_send.connect(SERVER, TCP_PORT)

        self.udp_recv = SocketController(SocketMode.UDP, km=self.km)
        self.udp_recv.bind('', 0)
        self.udp_port = self.udp_recv.getsockname()[1]
        self.udp_recv.start()

        # Helper function to convert samples to ms
        ms = lambda x: round(x * (44100 / 1000))
        # Setup a "safe" gate and compressor
        self.gate = Gate(ms(3.5), ms(10), ms(10), 950)
        self.comp = Compressor(ms(1), ms(100), 10000)

        # Setup the audio pipelines
        self.aio = AudioIO()
        self.aio.pipeline.insert(0, self.gate)
        self.aio.pipeline.insert(0, self.comp)
        self.aio.pipeline.append(TransmitAudio(self.udp_send))

        # If we aren't actually outputting anything, add a null sink.
        # This module never returns data, terminating the pipeline early.
        if no_output:
            self.aio.back_pipeline.insert(0, NullSink())
        if no_input:
            self.aio.pipeline.insert(0, NullSink())
        # self.aio.back_pipeline.insert(0, JitterBuffer())

    def kill(self, *_) -> None:
        """
        Sets both of the death flags for the client.
        """
        self._alive = False
        self.kill_me_now.set()

    def tcp_mainloop(self) -> None:
        """
        The main loop to handle TCP communications.
        A large amount of the TCP processing is handled by the socket
        controller, therefore this function serves to handle other fucntions
        such as adjusting pipeline modules.
        """
        while self._alive:
            # Wait for a new packet
            pkt = self.sock.get_packet(True)

            if pkt[2].opcode == SET_GATE:
                # Decode the payload
                try:
                    attack, hold, release, threshold, _ = (
                        struct.unpack('!4lH', pkt[2].payload)
                    )
                except:
                    continue

                # Reassign the gate parameters
                if attack != -1:
                    self.gate.gate.attack = attack
                if hold != -1:
                    self.gate.gate.hold = hold
                if release != -1:
                    self.gate.gate.release = release
                if threshold != -1:
                    self.gate.gate.threshold = threshold

                self.log.debug(f'Set gate to: {attack}, {hold}, {release}, '
                               f'{threshold}')
            elif pkt[2].opcode == SET_COMP:
                # Decode the payload
                try:
                    attack, release, threshold, _ = (
                        struct.unpack('!3lH', pkt[2].payload)
                    )
                except:
                    continue

                # Reassign the compressor parameters
                if attack != -1:
                    self.comp.comp.attack = attack
                if release != -1:
                    self.comp.comp.release = release
                if threshold != -1:
                    self.comp.comp.threshold = threshold

                self.log.debug(f'Set comp to: {attack}, {release}, '
                               f'{threshold}')

    def udp_mainloop(self) -> None:
        """
        The main loop to handle UDP communication.
        As with TCP, large portions of this are handled by the socket
        controller; the main function of this thread is to feed incomming
        audio into the pipeline.
        """
        self.aio.begin()

        while self._alive:
            # Wait for a new packet
            pkt = self.udp_recv.get_packet(True)

            if pkt[2].opcode == AUDIO:
                # Feed the pipeline
                self.aio.feed(pkt[2].payload, pkt[2])

    def mainloop(self) -> None:
        """
        The main loop for the client.
        Contrary to the naming convention, this function does no contain a
        classical loop. Instead, it spawns child threads, then waits for the
        death flag to be set.
        """
        # Perform TCP authentication before continuing
        self.client_id = self.sock.do_tcp_client_auth()
        # Inform the UDP controllers of the changes
        self.udp_send.client_id = self.client_id
        self.udp_recv.client_id = self.client_id

        self.log.info(f'Received client ID: {self.client_id}')

        # Inform the server as to the UDP port aquired by the client
        pld = struct.pack('!H', self.udp_port)
        self.sock.send_packet(REGISTER_UDP, pld)

        # Spawn the two child threads
        threading.Thread(target=self.tcp_mainloop, daemon=True).start()
        threading.Thread(target=self.udp_mainloop, daemon=True).start()

        # Wait for a death flag to be set.
        # The only case in which this flag should be set is in the case of an
        # unepxected disconnection from the server. In all other cases exiting
        # should be handled gracefully by a child thread.
        self.kill_me_now.wait()
        self.log.warning('Terminating client due to dropped connection.')


def main(*args, **kwargs) -> None:
    """
    Start a client instance, constantly respawning it in the case that it
    should terminate unexpectedly.
    """
    loggers.createFileLogger(__name__)
    log = loggers.getLogger(__name__)

    while True:
        try:
            # Create a new client instance, and start it
            Client(*args, **kwargs).mainloop()
        except ConnectionRefusedError:
            # Expected error. Show a critical warning.
            log.critical('Connecting to server failed!')
        except:
            # Unexpected error, print the traceback to the console.
            traceback.print_exc()
        log.info('Attempting to reconnect')


if __name__ == '__main__':
    main()
