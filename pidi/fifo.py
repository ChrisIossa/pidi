"""
Basic fifo handler.
"""
import os
import select


class FIFO:
    """
    Basic fifo handler.
    """
    def __init__(self, fifo_name, eol="\n", skip_create=False):
        self.fifo_name = fifo_name
        self.eol = eol

        if not skip_create:
            self._create()

        self._f = None
        self._buf = ""

    def _create(self):
        try:
            os.unlink(self.fifo_name)
        except (IOError, OSError):
            pass

        os.mkfifo(self.fifo_name)
        os.chmod(self.fifo_name, 0o777)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._f is not None:
            os.close(self._f)
            self._f = None

    def read(self):
        """Read data from the fifo."""
        if self._f is None:
            self._f = os.open(self.fifo_name, os.O_RDONLY | os.O_NONBLOCK)

        # Check for inbound command
        fifos, _, _ = select.select([self._f], [], [], 0)
        if self._f in fifos:
            while True:
                try:
                    char = os.read(self._f, 1).decode("UTF-8")
                except BlockingIOError:
                    return None
                if len(char) == 0:
                    return None
                self._buf += char
                if self._buf.endswith(self.eol):
                    buf = self._buf
                    self._buf = ""
                    return buf.strip()
        else:
            return None
