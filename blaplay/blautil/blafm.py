# blaplay, Copyright (C) 2012  Niklas Koep

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

import os
import shutil
import re
import json
import time
import threading
import Queue
import urllib
import urllib2
import httplib
import socket
import webbrowser
import cPickle as pickle

import gtk
import gobject

import blaplay
player = blaplay.bla.player
library = blaplay.bla.library
from blaplay.blacore import blacfg, blaconst
from blaplay import blautil
from blaplay.formats._identifiers import *

TIMEOUT = 5

scrobbler = None


def init():
    global scrobbler
    scrobbler = BlaScrobbler()
    player.connect("track_changed", scrobbler.submit_track)
    player.connect("track_stopped", scrobbler.submit_track)

def quote_url(url):
    return urllib2.quote(url.encode("utf-8"), safe=":/?=+&")

def create_popup_menu(track=None):
    user = blacfg.getstring("lastfm", "user")
    if not user:
        return None

    menu = gtk.Menu()

    # User profile
    m = gtk.MenuItem("View your profile")
    m.connect("activate",
              lambda *x: blautil.open_url("http://last.fm/user/%s" % user))
    menu.append(m)

    # Love/Unlove song
    artist = title = track_label = None
    if track is None:
        track = player.get_track()
    try:
        artist = track[ARTIST].replace(" ", "+")
        title =  track[TITLE].replace(" ", "+")
    except TypeError:
        return menu

    limit = 40
    track_label = "%s - %s" % (track[ARTIST], track[TITLE])
    if len(track_label) > limit:
        track_label = "%s..." % track_label[:limit]

    m = gtk.MenuItem("Love song \"%s\"" % track_label)
    m.connect("activate", lambda *x: love_unlove_song(track, unlove=False))
    menu.append(m)

    m = gtk.MenuItem("Unlove song \"%s\"" % track_label)
    m.connect("activate", lambda *x: love_unlove_song(track, unlove=True))
    menu.append(m)

    m = gtk.MenuItem("View song profile of \"%s\"" % track_label)
    m.connect(
        "activate",
        lambda *x: blautil.open_url("http://last.fm/music/%s/_/%s" %
                                    (artist, title)))
    menu.append(m)

    m = gtk.MenuItem("View artist profile of \"%s\"" % track[ARTIST])
    m.connect(
        "activate",
        lambda *x: blautil.open_url("http://last.fm/music/%s" % artist))
    menu.append(m)

    return menu

def parse_response(response, key):
    try:
        response = Response(response[key])
    except TypeError:
        response = ResponseError("Invalid key")
    except KeyError:
        response = ResponseError(response["message"])
    return response

def parse_socket_error_exception(exc):
    if not isinstance(exc, socket.error):
        raise TypeError("Expected socket.error, got %s" % type(exc))
    if isinstance(exc, socket.timeout):
        return ResponseError("%s" % exc)
    errno, errmsg = exc
    return ResponseError("%d: %s" % (errno, errmsg))

def post_message(params, key=None):
    class HTTPConnection(httplib.HTTPConnection):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("timeout", TIMEOUT)
            httplib.HTTPConnection.__init__(self, *args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def try_(func):
        try:
            return func()
        except socket.error as exc:
            return parse_socket_error_exception(exc)
        except httplib.HTTPException as exc:
            return ResponseError(exc)
        except ValueError as exc:
            # XXX: This could possibly catch errors in the BlaThread class'
            #      d'tor. Something to look into...
            return ResponseError(exc)

    params.append(("format", "json"))
    header = {"Content-type": "application/x-www-form-urlencoded"}

    with HTTPConnection("ws.audioscrobbler.com") as conn:
        r = try_(
            lambda: conn.request(
                "POST", "/2.0/?", urllib.urlencode(dict(params)), header))
        if isinstance(r, ResponseError):
            return r

        response = try_(lambda: conn.getresponse())
        if isinstance(response, ResponseError):
            return response

        response = try_(lambda: json.loads(response.read()))
        if isinstance(response, ResponseError):
            return response

    if key is not None:
        response = parse_response(response, key)
    else:
        response = Response(response)

    return response

def get_response(url, key):
    try:
        f = urllib2.urlopen(url, timeout=TIMEOUT)
    except socket.error as exc:
        return parse_socket_error_exception(exc)
    except urllib2.URLError as exc:
        return ResponseError(exc.reason)

    try:
        content = f.read()
        f.close()
        response = json.loads(content)
    except (socket.timeout, ValueError) as exc:
        return ResponseError(exc.message)

    return parse_response(response, key)

def get_image_url(image_urls):
    for dict_ in image_urls:
        if dict_["size"] == "extralarge":
            return dict_["#text"]
    return None

def retrieve_image(image_base, image_urls):
    image = None
    url = get_image_url(image_urls)
    if url:
        image, _ = urllib.urlretrieve(
            url, "%s.%s" % (image_base, blautil.get_extension(url)))
    return image

def get_cover(track, image_base):
    url = "%s&method=album.getinfo&album=%s&artist=%s&autocorrect=1" % (
        blaconst.LASTFM_BASEURL, track[ALBUM].replace("&", "and"),
        track[ARTIST].replace("&", "and"))
    url = quote_url(url)
    response = get_response(url, "album")
    if isinstance(response, ResponseError):
        print_d("Failed to retrieve cover: %s" % response)
        return None
    response = response.content

    name = os.path.basename(image_base)
    images = [os.path.join(blaconst.COVERS, f)
              for f in os.listdir(blaconst.COVERS) if f.startswith(name)]
    try:
        map(os.unlink, images)
    except IOError:
        pass

    try:
        image_urls = response["image"]
    except (TypeError, KeyError):
        return None
    return retrieve_image(image_base, image_urls)

def get_biography(track, image_base):
    url = quote_url("%s&method=artist.getinfo&artist=%s" % (
                    blaconst.LASTFM_BASEURL, track[ARTIST]))
    response = get_response(url, "artist")
    if isinstance(response, ResponseError):
        print_d("Failed to retrieve artist biography: %s" % response)
        return None, None
    response = response.content

    image = biography = None

    # Retrieve the artist image.
    try:
        image_urls = response["image"]
    except (TypeError, KeyError):
        pass
    else:
        image = retrieve_image(image_base, image_urls)

    # Retrieve the biography.
    try:
        biography = response["bio"]["content"]
    except (TypeError, KeyError):
        pass
    else:
        legal_notice = str(
            "User-contributed text is available under the Creative Commons "
            "By-SA License and may also be available under the GNU FDL.")
        biography = blautil.remove_html_tags(
            biography.replace(legal_notice, "").strip())

    return image, biography

def get_events(limit, recommended, city="", country=""):
    if recommended:
        session_key = BlaScrobbler.get_session_key()
        if not session_key:
            return events

        # Since this is an authorized service the location information from the
        # associated last.fm user account is used. Passing the country kwarg
        # doesn't allow specifying the city, so we just ignore it here.
        method = "user.getRecommendedEvents"
        params = [
            ("method", method), ("api_key", blaconst.LASTFM_APIKEY),
            ("sk", session_key), ("limit", str(limit))
        ]

        api_signature = sign_api_call(params)
        params.append(("api_sig", api_signature))
        response = post_message(params, "events")
    else:
        location = ", ".join([city, country] if country else [city])
        url = "%s&method=geo.getEvents&location=%s&limit=%d" % (
            blaconst.LASTFM_BASEURL, location, limit)
        url = quote_url(url)
        response = get_response(url, "events")

    if isinstance(response, ResponseError):
        print_d("Failed to retrieve recommended events: %s" % response)
        return None
    response = response.content

    return response["event"]

def get_new_releases(recommended=False):
    user = blacfg.getstring("lastfm", "user")
    if not user:
        return []

    url = "%s&method=user.getNewReleases&user=%s&userecs=%d" % (
        blaconst.LASTFM_BASEURL, user, int(recommended))
    url = quote_url(url)
    response = get_response(url, "albums")
    if isinstance(response, ResponseError):
        print_d("Failed to get new releases: %s" % response)
        return None
    response = response.content

    return response["album"]

def get_request_token():
    url = "%s&method=auth.gettoken" % blaconst.LASTFM_BASEURL
    response = get_response(url, "token")
    if isinstance(response, ResponseError):
        print_d("Failed to retrieve request token: %s" % response)
        return None

    return response.content

def sign_api_call(params):
    params.sort(key=lambda p: p[0].lower())
    string = "".join(["%s%s" % p for p in params])
    return blautil.md5("%s%s" % (string, blaconst.LASTFM_SECRET))

@blautil.thread
def love_unlove_song(track, unlove=False):
    if (not blacfg.getstring("lastfm", "user") or not track[ARTIST] or
        not track[TITLE]):
        return
    session_key = BlaScrobbler.get_session_key(create=True)
    if not session_key:
        return

    method = "track.unlove" if unlove else "track.love"
    params = [
        ("method", method), ("api_key", blaconst.LASTFM_APIKEY),
        ("artist", track[ARTIST]), ("track", track[TITLE]),
        ("sk", session_key)
    ]

    # Sign API call.
    api_signature = sign_api_call(params)
    params.append(("api_sig", api_signature))
    response = post_message(params)
    if isinstance(response, ResponseError):
        print_d("Failed to love/unlove song: %s" %  response)


class Response(object):
    def __init__(self, response):
        self.content = response

class ResponseError(Response):
    def __repr__(self):
        return str(self.content)

class BlaScrobbler(object):
    __requested_authorization = False
    __tid = -1
    __uri = None
    __start_time = 0
    __token = None
    __elapsed = 0
    __iterations = 0

    class SubmissionQueue(Queue.Queue):
        def __init__(self):
            Queue.Queue.__init__(self)
            self.__restore()
            self.__submit_scrobbles()

        @blautil.thread
        def __submit_scrobbles(self):
            while True:
                # Block until the first item arrives.
                items = [self.get()]
                # The API allows submission of up to 50 scrobbles in one POST.
                while len(items) <= 50:
                    try:
                        items.append(self.get_nowait())
                    except Queue.Empty:
                        break

                method = "track.scrobble"
                session_key = BlaScrobbler.get_session_key()
                if not session_key:
                    continue
                params = [
                    ("method", method), ("api_key", blaconst.LASTFM_APIKEY),
                    ("sk", session_key)
                ]
                for idx, item in enumerate(items):
                    uri, start_time = item
                    try:
                        track = library[uri]
                    except KeyError:
                        continue
                    params.extend(
                        [("artist[%d]" % idx, track[ARTIST]),
                         ("track[%d]" % idx, track[TITLE]),
                         ("timestamp[%d]" % idx, str(start_time))])
                    if track[ALBUM]:
                        params.append(("album[%d]" % idx, track[ALBUM]))
                    if track[ALBUM_ARTIST]:
                        params.append(
                            ("album_artist[%d]" % idx, track[ALBUM_ARTIST]))

                api_signature = sign_api_call(params)
                params.append(("api_sig", api_signature))

                @blautil.thread
                def post(params, items):
                    n_items = len(items)
                    response = post_message(params)
                    if isinstance(response, ResponseError):
                        print_w(
                            "Failed to submit %d scrobble(s) to last.fm: %s" %
                            (n_items, response))
                    else:
                        print_d("Submitted %d scrobble(s) to last.fm" %
                                n_items)
                post(params, items)

        def __restore(self):
            items = blautil.deserialize_from_file(blaconst.SCROBBLES_PATH)
            if items:
                print_d("Re-submitting %d queued scrobble(s)" % len(items))
                for item in items:
                    self.put_nowait(item)

        def save(self):
            items = []
            while True:
                try:
                    items.append(self.get_nowait())
                except Queue.Empty:
                    break
            if items:
                print_d("Saving %d unsubmitted scrobble(s)" % len(items))
            blautil.serialize_to_file(items, blaconst.SCROBBLES_PATH)

    def __init__(self):
        super(BlaScrobbler, self).__init__()
        blaplay.bla.register_for_cleanup(self)
        self.__queue = BlaScrobbler.SubmissionQueue()

    def __call__(self):
        self.__submit_last_track(True)

    @classmethod
    def __request_authorization(cls):
        from blaplay.blagui import blaguiutils
        response = blaguiutils.question_dialog(
            "last.fm authorization required", "In order to submit tracks to "
            "the last.fm scrobbler, blaplay needs to be authorized to use "
            "your account. Open the last.fm authorization page now?")
        if response == gtk.RESPONSE_YES:
            blautil.open_url(
                "http://www.last.fm/api/auth/?api_key=%s&token=%s" % (
                blaconst.LASTFM_APIKEY, cls.__token))
        return False

    def __passes_ignore(self, track):
        tokens = map(
            str.strip,
            filter(None,
                   blacfg.getstring("lastfm", "ignore.pattern").split(",")))
        res = [re.compile(t.decode("utf-8"), re.UNICODE | re.IGNORECASE)
               for t in tokens]
        for r in res:
            search = r.search
            for identifier in [ARTIST, TITLE]:
                if search(track[identifier]):
                    return False
        return True

    @blautil.thread
    def __update_now_playing(self):
        try:
            track = library[self.__uri]
        except KeyError:
            return
        if (not track[ARTIST] or not track[TITLE] or track[LENGTH] < 30 or
            not blacfg.getboolean("lastfm", "scrobble") or
            not blacfg.getboolean("lastfm", "now.playing")):
            return

        session_key = self.get_session_key()
        if not session_key:
            return

        method = "track.updateNowPlaying"
        params = [
            ("method", method), ("api_key", blaconst.LASTFM_APIKEY),
            ("artist", track[ARTIST]), ("track", track[TITLE]),
            ("sk", session_key)
        ]
        if track[ALBUM]:
            params.append(("album", track[ALBUM]))
        if track[ALBUM_ARTIST]:
            params.append(("album_artist", track[ALBUM_ARTIST]))

        # Sign API call.
        api_signature = sign_api_call(params)
        params.append(("api_sig", api_signature))
        response = post_message(params)
        if isinstance(response, ResponseError):
            print_d("Failed to update nowplaying: %s" % response)

    def __query_status(self):
        state = player.get_state()
        self.__iterations += 1
        # Wait 10~ seconds in between POSTs. Before actually posting an update
        # kill any remaining thread that still might be running.
        if self.__iterations % 10 == 0:
            try:
                self.__t.kill()
            except AttributeError:
                pass
            self.__t = self.__update_now_playing()
            self.__iterations = 0

        if state == blaconst.STATE_PLAYING:
            self.__elapsed += 1
        return state != blaconst.STATE_STOPPED

    def __submit_last_track(self, shutdown=False):
        if self.__uri:
            try:
                track = library[self.__uri]
            except KeyError:
                return
            # According to the last.fm API docs, only tracks longer than 30
            # seconds should be submitted, and only if min(len[s]/2, 240)
            # seconds of the track elapsed. Submission should be performed once
            # a track stops, e.g. on track changes or playback stops (and not
            # in paused states).
            if (track[LENGTH] > 30 and track[ARTIST] and track[TITLE] and
                blacfg.getboolean("lastfm", "scrobble") and
                (self.__elapsed > track[LENGTH] / 2 or self.__elapsed > 240)):
                print_d("Submitting track to scrobbler queue")
                self.__queue.put_nowait((self.__uri, self.__start_time))

        self.__uri = None
        if shutdown:
            print_i("Saving scrobbler queue")
            self.__queue.save()

    @classmethod
    def get_session_key(cls, create=False):
        session_key = blacfg.getstring("lastfm", "sessionkey")
        if session_key:
            return session_key
        if not create or cls.__requested_authorization:
            return None

        if not cls.__token:
            cls.__token = get_request_token()
            if not cls.__token:
                return None
            cls.__request_authorization()
            return None

        # FIXME: on start when there are unsubmitted scrobbles and no session
        #        key but a user name the request auth window will pop up which
        #        causes the statusbar to not update properly

        # TODO: check this more than once

        # We have a token, but it still might be unauthorized, i.e. we can't
        # create a session key from it. If that is the case ignore the
        # situation until the next start of blaplay. In order to avoid sending
        # requests to last.fm all the time we set an escape variable when we
        # encounter an unauthorized token.
        method = "auth.getSession"
        params = [
            ("method", method), ("api_key", blaconst.LASTFM_APIKEY),
            ("token", cls.__token)
        ]
        api_signature = sign_api_call(params)
        string = "&".join(["%s=%s" % p for p in params])
        url = "%s&api_sig=%s&%s" % (
            blaconst.LASTFM_BASEURL, api_signature, string)
        response = get_response(url, "session")
        if isinstance(response, ResponseError):
            session_key = None
            cls.__requested_authorization = True
        else:
            session_key = response.content["key"]
            blacfg.set("lastfm", "sessionkey", session_key)
        return session_key

    def submit_track(self, player):
        if (not blacfg.getstring("lastfm", "user") or
            not self.get_session_key(create=True)):
            return
        gobject.source_remove(self.__tid)

        # We request track submission on track changes. We don't have to check
        # here if a track passes the ignore settings as this is done when the
        # __uri attribute of the instance is set further down below.
        self.__submit_last_track()

        self.__elapsed = 0
        self.__iterations = 0
        track = player.get_track()
        if not track or player.radio or player.video:
            return

        if self.__passes_ignore(track):
            self.__uri = track.uri
            self.__start_time = int(time.time())
            self.__tid = gobject.timeout_add(1000, self.__query_status)
        else:
            self.__uri = None
            artist, title = track[ARTIST], track[TITLE]
            if artist and title:
                item = "%s - %s" % (artist, title)
            else:
                item = os.path.basename(track.uri)
            print_d("Not submitting \"%s\" to the scrobbler queue" % item)

