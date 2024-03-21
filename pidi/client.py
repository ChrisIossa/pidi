"""
Get song info.
"""
import xml
import shutil
from base64 import decodebytes
from pkg_resources import iter_entry_points

import mpd
import untangle
from .fifo import FIFO

from . import brainz
from . import util


def get_client_types():
    """Enumerate the pidi.plugin.client entry point and return installed client types."""
    client_types = {
        'mpd': ClientMPD,
        'ssnc': ClientShairportSync
    }

    for entry_point in iter_entry_points("pidi.plugin.client"):
        try:
            plugin = entry_point.load()
            client_types[plugin.option_name] = plugin
        except (ModuleNotFoundError, ImportError) as err:
            print("Error loading client plugin {entry_point}: {err}".format(
                entry_point=entry_point,
                err=err
            ))

    return client_types


class ClientShairportSync():
    """Client for ShairportSync metadata pipe."""
    # pylint: disable=too-many-instance-attributes
    def __init__(self, args):
        self.title = ""
        self.artist = ""
        self.album = ""
        self.time = 100
        self.state = ""
        self.volume = 0
        self.random = 0
        self.repeat = 0
        self.shuffle = 0
        self.album_art = ""
        self.pending_art = False

        self._update_pending = False

        self.fifo = FIFO(args.pipe, eol="</item>", skip_create=True)

    def add_args(argparse):  # pylint: disable=no-self-argument
        """Expand argparse instance with client-specific args."""
        argparse.add_argument(
            "--pipe",
            help="Pipe file for shairport sync metadata.",
            default="/tmp/shairport-sync-metadata")

    def status(self):
        """Return current status details."""
        return {
            "random": self.random,
            "repeat": self.repeat,
            "state": self.state,
            "volume": self.volume,
            "shuffle": self.shuffle
        }

    def currentsong(self):
        """Return current song details."""
        self._update_pending = False
        return {
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "time": self.time
        }

    def get_art(self, cache_dir, size):  # pylint: disable=unused-argument
        """Get the album art."""
        if self.album_art == "" or self.album_art is None:
            util.bytes_to_file(util.default_album_art(), cache_dir / "current.jpg")
            return

        util.bytes_to_file(self.album_art, cache_dir / "current.jpg")

        self.pending_art = False

    def update_pending(self):
        """Check if a new update is pending."""
        attempts = 0
        while True:
            data = self.fifo.read()
            if data is None or len(data) == 0:
                attempts += 1
                if attempts > 100:
                    return False
            else:
                self._parse_data(data)
                self._update_pending = True

        return self._update_pending

    def _parse_data(self, data):
        try:
            data = untangle.parse(data)
        except (xml.sax.SAXException, AttributeError) as exp:
            print(f"ClientShairportSync: failed to parse XML ({exp})")
            return

        dtype = bytes.fromhex(data.item.type.cdata).decode("ascii")
        dcode = bytes.fromhex(data.item.code.cdata).decode("ascii")

        data = getattr(data.item, "data", None)

        if data is not None:
            encoding = data["encoding"]
            data = data.cdata
            if encoding == "base64":
                data = decodebytes(data.encode("ascii"))

        if (dtype, dcode) == ("ssnc", "PICT"):
            self.pending_art = True
            self.album_art = data

        if (dtype, dcode) == ("core", "asal"):  # Album
            self.album = "" if data is None else data.decode("utf-8")

        if (dtype, dcode) == ("core", "asar"):  # Artist
            self.artist = "" if data is None else data.decode("utf-8")

        if (dtype, dcode) == ("core", "minm"):  # Song Name / Item
            self.title = "" if data is None else data.decode("utf-8")

        if (dtype, dcode) == ("ssnc", "prsm"):
            self.state = "play"

        if (dtype, dcode) == ("ssnc", "pend"):
            self.state = "stop"


class ClientMPD():
    """Client for MPD and MPD-like (such as Mopidy) music back-ends."""
    def __init__(self, args=None):
        """Initialize mpd."""
        self._client = mpd.MPDClient()
        self._current = None

        try:
            print(f"Connecting to mpd {args.server}:{args.port}")
            self._client.connect(args.server, args.port)
            print("Connected!")

        except ConnectionRefusedError as exc:
            raise RuntimeError("error: Connection refused to mpd/mopidy.") from exc

    def add_args(argparse):  # pylint: disable=no-self-argument
        """Expand argparse instance with client-specific args."""
        argparse.add_argument(
            "--port",
            help="Use a custom mpd port.",
            default=6600)

        argparse.add_argument(
            "--server",
            help="Use a remote server instead of localhost.",
            default="localhost")

    def currentsong(self):
        """Return current song details."""
        result = self._client.currentsong()  # pylint: disable=no-member
        return result

    def status(self):
        """Return current status details."""
        result = self._client.status()  # pylint: disable=no-member
        return result

    def update_pending(self, timeout=0.1):  # pylint: disable=unused-argument,no-self-use
        """Determine if anything has changed on the server."""
        return False

    def get_art(self, cache_dir, size, artServer="localhost", artPort=6081):
        """Get the album art."""
        song = self.currentsong()
        if len(song) < 2:
            print("mpd: Nothing currently playing.")
            util.bytes_to_file(util.default_album_art(), cache_dir / "current.jpg")
            return

        artist = song.get('artist')
        title = song.get('title')
        album = song.get('album', title)
        file_name = "{artist}_{album}_{size}.jpg".format(
            artist=artist,
            album=album,
            size=size
        ).replace("/", "")
        file_name = cache_dir / file_name

        if file_name.is_file():
            shutil.copy(file_name, cache_dir / "current.jpg")
            print("mpd: Found cached art.")

        else:
            print("mpd: Downloading album art...")

            brainz.init()
            album_art = brainz.get_cover(song, size)

            if not album_art:
                album_art = util.default_album_art()
            util.bytes_to_file(album_art, cache_dir / file_name)
            util.bytes_to_file(album_art, cache_dir / "current.jpg")

            print("mpd: Swapped art to {artist}, {title}.".format(
                artist=artist,
                title=title
            ))
