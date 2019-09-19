import unittest
import io

from voiplib.util.packets import Packet, PacketError


class TestPackets(unittest.TestCase):
    def test_forwards(self):
        packet = Packet(0, b'test data', 1563528913000, 1234)
        p_bytes = packet.digest()

        # Manually constructed packet
        self.assertEqual(p_bytes, b'\x00\x00\x88\x00h\x00\t\x04\xd2test data\x08\x11')

    def test_raises(self):
        packet = Packet(0, b'test data', 2e32, 0)
        with self.assertRaises(PacketError):
            packet.digest()

        packet = Packet(0, b'a' * 0xff_ff_ff, 1563528913000, 1234)
        with self.assertRaises(PacketError):
            packet.digest()

    def test_packet_crc(self):
        packet = Packet(0, b'test data', 1563528913000, 1234)
        p_bytes = packet.digest()

        # Invalidate the CRC
        p_bytes = p_bytes[:-packet.CRC_LENGTH] + (b'\0' * packet.CRC_LENGTH)

        with self.assertRaises(PacketError):
            Packet.from_bytes(p_bytes)

        # Simulated pipe
        pipe = io.BytesIO()
        pipe.write(p_bytes)
        pipe.seek(0)

        with self.assertRaises(PacketError):
            Packet.from_pipe(pipe)

    def test_reverse(self):
        # This is already tested in test_forwards and can be trusted
        packet = Packet(57, b'test data', 1563528913000, 1234)
        p_bytes = packet.digest()

        # Can we get the data back out?
        packet2 = Packet.from_bytes(p_bytes)
        self.assertEqual(packet2.opcode, 57)
        self.assertEqual(packet2.payload, b'test data')
        self.assertEqual(packet2.timestamp, 1563528913000)
        self.assertEqual(packet2.sequence, 1234)

    def test_pipes(self):
        # This is already tested in test_forwards and can be trusted
        packet = Packet(57, b'test data', 1563528913000, 1234)
        pipe = io.BytesIO()
        pipe.write(packet.digest())
        pipe.seek(0)

        # Using the BytesIO as a simulated pipe
        packet2 = Packet.from_pipe(pipe)
        self.assertEqual(packet2.opcode, 57)
        self.assertEqual(packet2.payload, b'test data')
        self.assertEqual(packet2.timestamp, 1563528913000)
        self.assertEqual(packet2.sequence, 1234)


if __name__ == '__main__':
    unittest.main()
