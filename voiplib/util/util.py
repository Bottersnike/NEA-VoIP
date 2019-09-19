def read(pipe, length):
    data = b''
    recv = getattr(pipe, 'recv', getattr(pipe, 'read', None))
    while len(data) < length:
        data += recv(length - len(data))
    return data
