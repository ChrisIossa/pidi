"""
LocalArt related functions.
"""
import time
import requests
from io import BytesIO
from PIL import Image

def get_cover(song, retry_delay=5, retries=5, server="localhost", port=6081):
    """Download the cover art."""
    albumArtist = song.get('albumartist')
    artist = song.get('artist')
    title = song.get('title')
    album = song.get('album', title)
    print("http://{0}:{1}/{2}/{3}/front.jpg".format(server,port,albumArtist,album))
    try:
        img = download_image("http://{0}:{1}/{2}/{3}/front.jpg".format(server,port,albumArtist,album),retry_delay,retries)
        if img is not None:
            im = Image.open(BytesIO(img.content))
            im.thumbnail((250,250), Image.ANTIALIAS)
            imgByteArr = BytesIO()
            im.save(imgByteArr, format=im.format)
            imgByteArr = imgByteArr.getvalue()
            return imgByteArr
        img = download_image("http://{0}:{1}/{2}/{3}/front.jpg".format(server,port,artist,album), retry_delay, retries)
        if img is not None:
            im = Image.open(BytesIO(img.content))
            im.thumbnail((250,250), Image.ANTIALIAS)
            imgByteArr = BytesIO()
            im.save(imgByteArr, format=im.format)
            imgByteArr = imgByteArr.getvalue()
            return imgByteArr
        return img
    except:
        print("error: Couldn't find album art for",
              "{artist} - {album}".format(artist=artist, album=album))

def download_image(image_url,retry_delay,retries):
    try:
        img=requests.get(image_url, stream=True)
        img.raise_for_status()
        return img
    except requests.exceptions.HTTPError:
        return None
    except requests.exceptions.RequestException:
        if retries == 0:
            return None
        time.sleep(retry_delay)
        download_image(image_url, retry_delay, retries=retries - 1)

    
    
        

    
