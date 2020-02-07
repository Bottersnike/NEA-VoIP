from datetime import datetime
from typing import Tuple
import inspect
import sys

from .const import INFO


class Logger:
    FORMAT = '[{level}] [{name}:{lineno}] {message}'
    LEVEL = INFO

    def __init__(self) -> None:
        self.outputs = [sys.stderr]

    def log(self, msg: str, level: Tuple[int, str], name: str) -> None:
        """
        Write an entry to the designated logging outputs.

        :param str msg: The message to log
        :param tuple level: The logging level
        :param str name: The name of the logger performing the log
        """
        if level[0] < self.LEVEL[0]:
            return
        caller = inspect.stack()[3]

        formatting = {
            'level': level[1],
            'name': name,
            'message': msg,
            'time': str(datetime.now()),

            'lineno': caller.lineno,
            'filename': caller.filename,
            'function': caller.function,
            'module': inspect.getmodule(caller.frame.f_code).__name__,
        }
        msg = self.FORMAT.format(**formatting)

        self._log(msg + '\n')

    def _log(self, msg: str) -> None:
        """
        Write a raw log message to all of the current outputs

        :param str msg: The message to write
        """
        for i in self.outputs:
            i.write(msg)
