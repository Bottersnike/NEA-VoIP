from typing import BinaryIO
from io import BytesIO
import struct


class WAVFile:
    PCM = 1
    Mono = 1
    Stereo = 2

    def __init__(self, file_obj: BinaryIO, rate: int=44100, channels: int=Mono,
                 bps: int=16, new: bool=True) -> None:
        self.file = file_obj
        self.rate = rate
        self.channels = channels
        self.bps = bps
        self.new = new
    
    def build_chunk(self, name: bytes, data: bytes) -> bytes:
        """
        Construct a RIFF chunk. This will build the header then append the
        required data.

        :param bytes name: The name of the chunk. Max 4 characters.
        :param bytes data: The body data of the chunk
        """
        chunk = name.ljust(4, b' ')[:4]
        chunk += struct.pack('<I', len(data))
        return chunk + data
    
    def write(self, data: bytes) -> int:
        """
        Write a sequence of PCM data to a wav file

        :param bytes data: The data to write/append to the file    
        """
        if self.new:
            # The file didn't exist, so create a new header
            fmt = struct.pack(
                '<HHIIHH', self.PCM, self.channels,
                self.rate, int(self.rate * self.channels * (self.bps / 8)),
                int(self.channels * (self.bps / 8)), self.bps
            )
            # Setup the header header (yes, that's not a typo)
            riff = b'WAVE'
            riff += self.build_chunk(b'fmt', fmt)
            riff += self.build_chunk(b'data', data)

            # Write all the headers and data to the file
            return self.file.write(self.build_chunk(b'RIFF', riff))
        else:
            # Jump to the 4th byte and read the file length
            self.file.seek(4)
            lbytes = self.file.read(4)
            if len(lbytes) != 4:
                # Failed to parse, overwrite the whole file
                self.new = True
                self.file.seek(0)
                return self.write(data)
            length = struct.unpack('<I', lbytes)[0]

            # Write the new length
            self.file.seek(4)
            self.file.write(struct.pack('<I', length + len(data)))
            # Read the length of the PCM data
            self.file.seek(40)

            dlb = self.file.read(4)
            if len(dlb) != 4:
                # Failed to parse, overwrite the whole file
                self.new = True
                self.file.seek(0)
                return self.write(data)
            dl = struct.unpack('<I', dlb)[0]

            self.file.seek(40)
            # Write the new length
            self.file.write(struct.pack('<I', dl + len(data)))
            # Seek to after existing data
            self.file.seek(dl)
            # Write the additional data to the file
            self.file.write(data)
            # Truncate the file at the current position to avoid trailing data
            self.file.truncate()
            return self.file.tell()    
