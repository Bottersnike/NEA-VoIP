from datetime import datetime
import os


class FileOutput:
    def __init__(self, name: str) -> None:
        # Parse the given filename
        self.path = os.path.abspath(name)
        dirname = os.path.dirname(self.path)

        # Make sure we are able to create the file
        os.makedirs(dirname, exist_ok=True)

        # Add a log header for clarity
        with open(self.path, 'a') as f:
            f.write('\n')
            f.write('  **** LOGS START AT {} ****\n'.format(datetime.now()))
            f.write('\n')

    def write(self, msg: str) -> None:
        """
        Write a string to the output file

        :param str msg: The message to write
        """
        with open(self.path, 'a') as f:
            f.write(msg)
