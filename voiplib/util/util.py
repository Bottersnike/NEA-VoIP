def read(pipe, length: int) -> bytes:
    """
    Read data from a given unput until the required amount of data has been
    read. Required in cases such as sockets where a read operationg will not
    always return all of the required data, due to buffering.
    """
    data = b''
    recv = getattr(pipe, 'recv', getattr(pipe, 'read', None))
    while len(data) < length:
        data += recv(length - len(data))
    return data
