import os

from .file_output import FileOutput
from .log_module import LogModule
from .logger import Logger
from .const import *


# Create a modul-global logging handler
loggerInst = Logger()


def getLogger(name: str) -> LogModule:
    """
    Create a new named logger instance

    :param str name: The name to associate with the logger
    """
    return LogModule(loggerInst, name)


def createFileLogger(name: str) -> None:
    """
    Create and register a new file logging output.

    :param str name: The name to use for the file. `.log` will be appended
        and additional directories created as required.
    """
    name = os.path.join(LOG_DIR, name + '.log')
    loggerInst.outputs.append(FileOutput(name))
