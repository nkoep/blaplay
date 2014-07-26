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
# XXX: Get rid of this.
player = blaplay.bla.player
from blaplay import blautil
from blaplay.blacore import blacfg, blaconst
from blaplay.blagui import blaguiutil
from blaplay.formats._identifiers import *

TIMEOUT = 5

# XXX: Get rid of this.
scrobbler = None


def init(library, player):
    global scrobbler
    scrobbler = BlaScrobbler(library)

    BlaFm(library, player, scrobbler)

# TODO: Rename this to create_submenu.
def create_popup_menu(track=None):
    user = blacfg.getstring("lastfm", "user")
    if not user:
        return None

    menu = blaguiutil.BlaMenu()

    # User profile
    menu.append_item("View your profile", blautil.open_url,
                     "http://last.fm/user/%s" % user)

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
    menu.append_item("Love song \"%s\"" % track_label, _love_song, track)
    menu.append_item("Unlove song \"%s\"" % track_label, _unlove_song, track)
    menu.append_item(
        "View song profile of \"%s\"" % track_label, blautil.open_url,
        "http://last.fm/music/%s/_/%s" % (artist, title))
    menu.append_item("View artist profile of \"%s\"" % track[ARTIST],
                     blautil.open_url, "http://last.fm/music/%s" % artist)

    return menu

def _parse_response(response, key):
    try:
        response = _Response(response[key])
    except TypeError:
        response = _ResponseError("Invalid key")
    except KeyError:
        response = _ResponseError(response["message"])
    return response

def _parse_socket_error_exception(exc):
    if not isinstance(exc, socket.error):
        raise TypeError("Expected socket.error, got %s" % type(exc))
    if isinstance(exc, socket.timeout):
        return _ResponseError("%s" % exc)
    errno, errmsg = exc
    return _ResponseError("%d: %s" % (errno, errmsg))

def _post_message(params, key=None):
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
            return _parse_socket_error_exception(exc)
        except httplib.HTTPException as exc:
            return _ResponseError(exc)
        except ValueError as exc:
            # XXX: This could possibly catch errors in the BlaThread class'
            #      d'tor. Something to look into...
            return _ResponseError(exc)

    params.append(("format", "json"))
    header = {"Content-type": "application/x-www-form-urlencoded"}

    with HTTPConnection("ws.audioscrobbler.com") as conn:
        r = try_(
            lambda: conn.request(
                "POST", "/2.0/?", urllib.urlencode(dict(params)), header))
        if isinstance(r, _ResponseError):
            return r

        response = try_(lambda: conn.getresponse())
        if isinstance(response, _ResponseError):
            return response

        response = try_(lambda: json.loads(response.read()))
        if isinstance(response, _ResponseError):
            return response

    if key is not None:
        response = _parse_response(response, key)
    else:
        response = _Response(response)

    return response

def _get_response(url, key):
    try:
        f = urllib2.urlopen(url, timeout=TIMEOUT)
    except socket.error as exc:
        return _parse_socket_error_exception(exc)
    except urllib2.URLError as exc:
        return _ResponseError(exc.reason)

    try:
        content = f.read()
        f.close()
        response = json.loads(content)
    except (socket.timeout, ValueError) as exc:
        return _ResponseError(exc.message)

    return _parse_response(response, key)

def _get_image_url(image_urls):
    for dict_ in image_urls:
        if dict_["size"] == "extralarge":
            return dict_["#text"]
    return None

def _retrieve_image(image_base, image_urls):
    image = None
    url = _get_image_url(image_urls)
    if url:
        image, _ = urllib.urlretrieve(
            url, "%s.%s" % (image_base, blautil.get_extension(url)))
    return image

def _quote_url(url):
    return urllib2.quote(url.encode("utf-8"), safe=":/?=+&")

def get_cover(track, image_base):
    url = "%s&method=album.getinfo&album=%s&artist=%s&autocorrect=1" % (
        blaconst.LASTFM_BASEURL, track[ALBUM].replace("&", "and"),
        track[ARTIST].replace("&", "and"))
    url = _quote_url(url)
    response = _get_response(url, "album")
    if isinstance(response, _ResponseError):
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
    return _retrieve_image(image_base, image_urls)

def _get_request_token():
    url = "%s&method=auth.gettoken" % blaconst.LASTFM_BASEURL
    response = _get_response(url, "token")
    if isinstance(response, _ResponseError):
        print_d("Failed to retrieve request token: %s" % response)
        return None
    return response.content

def _sign_api_call(params):
    params.sort(key=lambda p: p[0].lower())
    string = "".join(["%s%s" % (key, value) for key, value in params])
    return blautil.md5("%s%s" % (string, blaconst.LASTFM_SECRET))

@blautil.thread
def _love_unlove_song(track, method):
    if (not blacfg.getstring("lastfm", "user") or not track[ARTIST] or
        not track[TITLE]):
        return
    session_key = scrobbler.get_session_key(create=True)
    if not session_key:
        return

    method = "track.%s" % method
    params = [
        ("method", method), ("api_key", blaconst.LASTFM_APIKEY),
        ("artist", track[ARTIST]), ("track", track[TITLE]),
        ("sk", session_key)
    ]

    # Sign API call.
    api_signature = _sign_api_call(params)
    params.append(("api_sig", api_signature))
    response = _post_message(params)
    if isinstance(response, _ResponseError):
        print_d("Failed to love/unlove song: %s" %  response)

def _love_song(track):
    _love_unlove_song(track, "love")

def _unlove_song(track):
    _love_unlove_song(track, "unlove")

class _Response(object):
    def __init__(self, response):
        self.content = response

class _ResponseError(_Response):
    def __repr__(self):
        return str(self.content)

class _SubmissionQueue(Queue.Queue):
    def __init__(self, library):
        Queue.Queue.__init__(self)
        self._library = library
        self._restore()
        # XXX: Here's the thing: _SubmissionQueue gets created in the c'tor of
        #      BlaScrobbler. This means that by the time we call
        #      `submit_scrobbles' here, the global variable `scrobbler' isn't
        #      assigned yet. However, to get a last.fm session key we already
        #      need `scrobbler' in said method. Bottom line: we need to rethink
        #      the whole dependency graph of classes in this module.
        self._submit_scrobbles()

    @blautil.thread
    def _submit_scrobbles(self):
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
            # XXX: This is an artifact of having `scrobbler' be defined as a
            #      global. See comment in `__init__'.
            try:
                session_key = scrobbler.get_session_key()
            except AttributeError:
                continue
            if not session_key:
                continue
            params = [
                ("method", method), ("api_key", blaconst.LASTFM_APIKEY),
                ("sk", session_key)
            ]
            for idx, item in enumerate(items):
                uri, start_time = item
                try:
                    track = self._library[uri]
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

            api_signature = _sign_api_call(params)
            params.append(("api_sig", api_signature))

            @blautil.thread
            def post(params, items):
                n_items = len(items)
                response = _post_message(params)
                if isinstance(response, _ResponseError):
                    print_w(
                        "Failed to submit %d scrobble(s) to last.fm: %s" %
                        (n_items, response))
                else:
                    print_d("Submitted %d scrobble(s) to last.fm" %
                            n_items)
            post(params, items)

    def _restore(self):
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

class BlaScrobbler(object):
    def __init__(self, library):
        super(BlaScrobbler, self).__init__()
        self._library = library

        self._requested_authorization = False
        self._timeout_id = 0
        self._uri = None
        self._start_time = 0
        self._token = None
        self._time_elapsed = 0
        self._iterations = 0
        self._thread = None

        self._queue = _SubmissionQueue(library)
        def pre_shutdown_hook():
            self._submit_last_track(True)
        blaplay.bla.add_pre_shutdown_hook(pre_shutdown_hook)

    def _request_authorization(self):
        from blaplay.blagui import blaguiutil
        response = blaguiutil.question_dialog(
            "last.fm authorization required", "In order to submit tracks to "
            "the last.fm scrobbler, blaplay needs to be authorized to use "
            "your account. Open the last.fm authorization page now?")
        if response == gtk.RESPONSE_YES:
            blautil.open_url(
                "http://www.last.fm/api/auth/?api_key=%s&token=%s" % (
                blaconst.LASTFM_APIKEY, self._token))
        return False

    def _passes_ignore(self, track):
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
    def _update_now_playing(self):
        try:
            track = self._library[self._uri]
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
        api_signature = _sign_api_call(params)
        params.append(("api_sig", api_signature))
        response = _post_message(params)
        if isinstance(response, _ResponseError):
            print_d("Failed to update nowplaying: %s" % response)

    def _query_status(self):
        state = player.get_state()
        self._iterations += 1
        # Wait 10~ seconds in between POSTs. Before actually posting an update
        # kill any remaining thread that still might be running.
        if self._iterations % 10 == 0:
            if self._thread is not None:
                self._thread.kill()
            self._thread = self._update_now_playing()
            self._iterations = 0

        if state == blaconst.STATE_PLAYING:
            self._time_elapsed += 1
        should_call_again = state != blaconst.STATE_STOPPED
        if not should_call_again:
            self._timeout_id = 0
        return should_call_again

    def _submit_last_track(self, shutdown=False):
        if self._uri:
            try:
                track = self._library[self._uri]
            except KeyError:
                return
            # According to the last.fm API docs, only tracks longer than 30
            # seconds should be submitted, and only if min(len[s]/2, 240)
            # seconds of the track elapsed. Submission should be performed once
            # a track stops, e.g. on track changes or playback stops (and not
            # in paused states).
            if (track[LENGTH] > 30 and track[ARTIST] and track[TITLE] and
                blacfg.getboolean("lastfm", "scrobble") and
                (self._time_elapsed > track[LENGTH] / 2 or
                 self._time_elapsed > 240)):
                print_d("Submitting track to scrobbler queue")
                self._queue.put_nowait((self._uri, self._start_time))

        self._uri = None
        if shutdown:
            print_i("Saving scrobbler queue")
            self._queue.save()

    def get_session_key(self, create=False):
        session_key = blacfg.getstring("lastfm", "sessionkey")
        if session_key:
            return session_key
        if not create or self._requested_authorization:
            return None

        if not self._token:
            self._token = _get_request_token()
            if not self._token:
                return None
            self._request_authorization()
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
            ("token", self._token)
        ]
        api_signature = _sign_api_call(params)
        string = "&".join(["%s=%s" % p for p in params])
        url = "%s&api_sig=%s&%s" % (
            blaconst.LASTFM_BASEURL, api_signature, string)
        response = _get_response(url, "session")
        if isinstance(response, _ResponseError):
            session_key = None
            self._requested_authorization = True
        else:
            session_key = response.content["key"]
            blacfg.set_("lastfm", "sessionkey", session_key)
        return session_key

    def submit_track(self, player):
        if (not blacfg.getstring("lastfm", "user") or
            not self.get_session_key(create=True)):
            return
        if self._timeout_id:
            gobject.source_remove(self._timeout_id)
            self._timeout_id = 0

        # We request track submission on track changes. We don't have to check
        # here if a track passes the ignore settings as this is done when the
        # _uri attribute of the instance is set further down below.
        self._submit_last_track()

        self._time_elapsed = 0
        self._iterations = 0
        track = player.get_track()
        if not track or player.video:
            return

        if self._passes_ignore(track):
            self._uri = track.uri
            self._start_time = int(time.time())
            self._timeout_id = gobject.timeout_add(1000, self._query_status)
        else:
            self._uri = None
            artist, title = track[ARTIST], track[TITLE]
            if artist and title:
                item = "%s - %s" % (artist, title)
            else:
                item = os.path.basename(track.uri)
            print_d("Not submitting \"%s\" to the scrobbler queue" % item)

class BlaFm(object):
    def __init__(self, library, player, scrobbler):
        self._library = library
        self._player = player
        self._scrobbler = scrobbler

        player.connect("track-changed", scrobbler.submit_track)
        player.connect("track-stopped", scrobbler.submit_track)

