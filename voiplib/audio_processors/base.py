import abc


class AudioProcessor(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def process(self, data, packet, amp):
        pass

    def __call__(self, data, *args):
        return self.process(data, *args)

    def clone(self):
        return self.__class__()
