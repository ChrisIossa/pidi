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
import json
import websocket
import threading
import time

def get_client_types():
    """Enumerate the pidi.plugin.client entry point and return installed client types."""
    client_types = {
        'mpd': ClientMPD,
        'ssnc': ClientShairportSync,
        'snapcast': ClientSnapcast
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

class ClientSnapcast():
    """Client for MPD and MPD-like (such as Mopidy) music back-ends."""
    def __init__(self, args=None):
        """Initialize mpd."""
        
        
        self.client_id = args.client_id
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
        self.album_art_url = ""
        self.pending_art = False
        
        self._update_pending = False
        

        self._req_id = 0
        self._stream_id = ''
        self._request_map = {}
        self.websocket = websocket.WebSocketApp("ws://" + args.server + ":" + str(args.port) + "/jsonrpc",
                                                on_message=self.on_ws_message,
                                                on_error=self.on_ws_error,
                                                on_open=self.on_ws_open,
                                                on_close=self.on_ws_close)
        self.websocket_thread = threading.Thread(
            target=self.websocket_loop, args=())
        self.websocket_thread.name = "SnapcastRpcWebsocketWrapper"
        self.websocket_thread.start()
    
    def websocket_loop(self):
        print("Started SnapcastRpcWebsocketWrapper loop")
        while True:
            try:
                self.websocket.run_forever()
                time.sleep(1)
            except Exception as e:
                logger.info(f"Exception: {str(e)}")
                self.websocket.close()
        print("Ending SnapcastRpcWebsocketWrapper loop")
    
    def __get_stream_id_from_server_status(self, status, client_id):
        try:
            for group in status['server']['groups']:
                for client in group['clients']:
                    if client['id'] == client_id:
                        return group['stream_id']
            for group in status['server']['groups']:
                for client in group['clients']:
                    if client['name'] == client_id:
                        return group['stream_id']
        except:
            print('Failed to parse server status')
        print(f'Failed to get stream id for client {client_id}')
        return None
    
    def __update_metadata(self, meta):
        try:
            if meta is None:
                meta = {}
            print(f'Meta: "{meta}"')
            
            self.title = meta.get('title') or ""
            self.artist = ''.join(meta.get('albumArtist') or meta.get('artist') or [''])
            self.album = meta.get('album') or ''
            self.album_art_url = meta.get('artUrl')
            self.pending_art = True
            self._update_pending = True
        except Exception as e:
            print(f'Error in update_metadata: {str(e)}')

    def __update_properties(self, props):
        try:
            if props is None:
                props = {}
            print(f'Properties: "{props}"')
            # store the last receive time stamp for better position estimation
            if 'position' in props:
                props['_received'] = time.time()
            # ignore "internal" properties, starting with "_"
            
            
            self.state = {'playing': 'play', 'paused': 'pause', 'stopped': 'stop', '':''}[(props.get('playbackStatus') or '')]
            print(f"State: {self.state}")
            self.volume = props.get('volume') or 0
            self.shuffle = props.get('shuffle') or False
            self.time = props.get('position') or 100
            if 'metadata' in props:
                self.__update_metadata(props.get('metadata', None))
            self._update_pending = True
        except Exception as e:
            print(f'Error in update_properties: {str(e)}')
    
    def on_ws_message(self, ws, message):
        # TODO: error handling
        print(f'Snapcast RPC websocket message received: {message}')
        jmsg = json.loads(message)
        if 'id' in jmsg:
            id = jmsg['id']
            if id in self._request_map:
                request = self._request_map[id]
                del self._request_map[id]
                print(f'Received response to {request}')
                if request == 'Server.GetStatus':
                    self._stream_id = self.__get_stream_id_from_server_status(
                        jmsg['result'], self.client_id)
                    print(f'Stream id: {self._stream_id}')
                    for stream in jmsg['result']['server']['streams']:
                        if stream['id'] == self._stream_id:
                            if 'properties' in stream:
                                self.__update_properties(stream['properties'])
                            break
        elif jmsg['method'] == "Server.OnUpdate":
            self._stream_id = self.__get_stream_id_from_server_status(
                jmsg['params'], self.client_id)
            print(f'Stream id: {self._stream_id}')
        elif jmsg['method'] == "Group.OnStreamChanged":
            self.send_request("Server.GetStatus")
        elif jmsg["method"] == "Stream.OnProperties":
            stream_id = jmsg["params"]["id"]
            print(
                f'Stream properties changed for "{stream_id}"')
            if self._stream_id != stream_id:
                return
            props = jmsg["params"]["properties"]
            self.__update_properties(props)

    def on_ws_error(self, ws, error):
        print("Snapcast RPC websocket error")
        print(error)

    def on_ws_open(self, ws):
        print("Snapcast RPC websocket opened")

        # Export our DBUS service
        self.send_request("Server.GetStatus")
        

    def on_ws_close(self, ws):
        print("Snapcast RPC websocket closed")
        
    def send_request(self, method, params=None):
        j = {"id": self._req_id, "jsonrpc": "2.0", "method": str(method)}
        if not params is None:
            j["params"] = params
        print(f'send_request: {j}')
        result = self._req_id
        self._request_map[result] = str(method)
        self._req_id += 1
        self.websocket.send(json.dumps(j))
        return result        
    
    def stop(self):
        self.websocket.keep_running = False
        print("Waiting for websocket thread to exit")
        # self.websocket_thread.join()
                            
    def add_args(argparse):  # pylint: disable=no-self-argument
        """Expand argparse instance with client-specific args."""
        argparse.add_argument(
            "--port",
            help="Use a custom snapcast port.",
            default=1780)

        argparse.add_argument(
            "--server",
            help="Use a remote server instead of localhost.",
            default="localhost")
        
        argparse.add_argument(
            "--client-id",
            help="The id of the running snapcast client.",
            default="localhost")

    def currentsong(self):
        """Return current song details."""
        self._update_pending = False
        return {
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "time": self.time
        }

    def status(self):
        """Return current status details."""
        return {
            "random": self.random,
            "repeat": self.repeat,
            "state": self.state,
            "volume": self.volume,
            "shuffle": self.shuffle
        }

    def update_pending(self, timeout=0.1):  # pylint: disable=unused-argument,no-self-use
        """Determine if anything has changed on the server."""
        return self.update_pending

    def get_art(self, cache_dir, size):
        """Get the album art."""
        
        song = self.currentsong()
        
        if len(f"{song.get('artist')} - {song.get('album')} - {song.get('title')}") < 9:
            print("Snapcast: Nothing currently playing.")
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
            print("Snapcast: Found cached art.")
        else:
            album_art = None
            if self.album_art_url is not None:
                print("Using art from Snapcast")
                print("Snapcast: Downloading album art provided by Snapcast...")
                album_art = util.download_image(self.album_art_url)
            if not album_art:
                print("Snapcast: Getting art from MusicBrainz")            
                brainz.init()
                album_art = brainz.get_cover(song, size)

            if not album_art:
                album_art = util.default_album_art()
            util.bytes_to_file(album_art, cache_dir / file_name)
            util.bytes_to_file(album_art, cache_dir / "current.jpg")

        print("Snapcast: Swapped art to {artist}, {title}.".format(
            artist=artist,
            title=title
        ))
        self.pending_art = False
        
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

    def get_art(self, cache_dir, size):
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
        self.pending_art = False