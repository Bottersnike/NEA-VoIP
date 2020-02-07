import time

from .database import Histories


EVENT_CONN = 0
EVENT_DCON = 1
EVENT_TEXT = 2


def insert(device, event, details=''):
    history = Histories(device, int(time.time() * 1000), event, details)
    Histories.insert(history)


def find(device):
    return Histories.select(device=device)
