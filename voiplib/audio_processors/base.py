class AudioProcessor:
    def process(self, data, packet, amp):
        return data

    def __call__(self, data, *args):
        return self.process(data, *args)

    def clone(self):
        return self.__class__()
