from typing import Tuple

from .logger import Logger
from .const import *


class LogModule:
    def __init__(self, logger: Logger, name: str) -> None:
        self.logger = logger
        self.name = name

    def log(self, level: Tuple[int, str], msg: str) -> None:
        """
        Log a message to the logger

        :param tuple level: The log level to use
        :param str msg: The message to log
        """
        self.logger.log(msg, level, self.name)

    def debug(self, msg: str) -> None:
        """
        Log a message with level "DEBUG"

        :param str msg: The message to log
        """
        self.log(DEBUG, msg)

    def info(self, msg: str) -> None:
        """
        Log a message with level "INFO"

        :param str msg: The message to log
        """
        self.log(INFO, msg)

    def warning(self, msg: str) -> None:
        """
        Log a message with level "WARNING"

        :param str msg: The message to log
        """
        self.log(WARNING, msg)

    def error(self, msg: str) -> None:
        """
        Log a message with level "ERROR"

        :param str msg: The message to log
        """
        self.log(ERROR, msg)

    def critical(self, msg: str) -> None:
        """
        Log a message with level "CRITICAL"

        :param str msg: The message to log
        """
        self.log(CRITICAL, msg)
