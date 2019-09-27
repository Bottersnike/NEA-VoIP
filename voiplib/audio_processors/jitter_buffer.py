import heapq

from .base import AudioProcessor


class JitterBuffer(AudioProcessor):
    ROLLOVER = 50
    BUFFER = 5

    def __init__(self):
        self.latest = 0
        self.heap = []

    def process(self, data, packet, *_):
        if self.ROLLOVER < packet.sequence < self.latest:
            return None
        heapq.heappush(self.heap, (packet.sequence, data))

        while len(self.heap) >= self.BUFFER:
            popped = heapq.heappop(self.heap)
            if self.latest >= popped[0] > self.ROLLOVER:
                continue
            if self.latest == 0:
                self.latest = popped[0]
            else:
                self.latest += 1
            # if self.latest != popped[0]:
            #    heapq.heappush(self.heap, (packet.sequence, data))
            return popped[1]
        return None
