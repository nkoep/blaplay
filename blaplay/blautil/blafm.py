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
import urllib
import urllib2
import httplib
import socket
import webbrowser
quote_url = lambda url: urllib2.quote(url.encode("utf-8"), safe=":/?=+&")
import cPickle as pickle

import gtk
import gobject

import blaplay
player = blaplay.bla.player
library = blaplay.bla.library
from blaplay.blacore import blacfg, blaconst
from blaplay import blautil
from blaplay.formats._identifiers import *

scrobbler = None

TIMEOUT = 10
LEGAL_NOTICE = str(
    "User-contributed text is available under the Creative Commons By-SA "
    "License and may also be available under the GNU FDL."
)


def init():
    global scrobbler
    scrobbler = BlaScrobbler()
    player.connect("track_changed", scrobbler.submit_track)
    player.connect("track_stopped", scrobbler.submit_track)

def get_popup_menu(track=None):
    user = blacfg.getstring("lastfm", "user")
    if track is None: track = player.get_track()
    if not track and not user: return None

    menu = gtk.Menu()
    if user:
        m = gtk.MenuItem("View your profile")
        m.connect("activate",
                lambda *x: blautil.open_url("http://last.fm/user/%s" % user))
        menu.append(m)

        m = gtk.MenuItem("Love song")
        m.connect("activate", lambda *x: love_unlove_song(track, unlove=False))
        menu.append(m)

        m = gtk.MenuItem("Unlove song")
        m.connect("activate", lambda *x: love_unlove_song(track, unlove=True))
        menu.append(m)

    m = gtk.MenuItem("View song profile")

    if track:
        m.connect("activate",
                lambda *x: blautil.open_url("http://last.fm/music/%s/_/%s" %
                (track[ARTIST].replace(" ", "+"),
                track[TITLE].replace(" ", "+")))
        )
        menu.append(m)

        m = gtk.MenuItem("View artist profile")
        m.connect("activate", lambda *x: blautil.open_url(
                "http://last.fm/music/%s" % track[ARTIST].replace(" ", "+")))
        menu.append(m)

    return menu

def post_message(params):
    error, response = 1, "Socket error"
    conn = httplib.HTTPConnection("ws.audioscrobbler.com")
    params.append(("format", "json"))
    header = {"Content-type": "application/x-www-form-urlencoded"}
    try: conn.request("POST", "/2.0/?", urllib.urlencode(dict(params)), header)
    except (socket.gaierror, socket.error) as (error, response): pass
    else:
        try: response = conn.getresponse()
        except (httplib.BadStatusLine, socket.error): pass
        else:
            try: response = json.loads(response.read())
            except (socket.timeout, ValueError):
                error, response = response.status, response.reason
            else: error, response = 0, response
    conn.close()
    return error, response

def get_response(url, key):
    error, response = 0, None
    try: f = urllib2.urlopen(url, timeout=TIMEOUT)
    except (socket.timeout, urllib2.URLError, IOError): pass
    else:
        try: response = json.loads(f.read())
        except (socket.timeout, ValueError): pass
        else:
            f.close()
            try: response = response[key]
            except TypeError: pass
            except KeyError:
                error = response["error"]
                response = response["message"]
    return error, response

def get_image_url(images):
    for image_dict in images:
        if image_dict["size"] == "extralarge":
            url = image_dict["#text"]
            break
    else: raise ValueError("No extralarge cover found")
    return url

def get_cover(track, image_base):
    path, cover = None, None
    url = "%s&method=album.getinfo&album=%s&artist=%s&autocorrect=1" % (
            blaconst.LASTFM_BASEURL, track[ALBUM].replace("&", "and"),
            track[ARTIST].replace("&", "and")
    )
    url = quote_url(url)
    error, response = get_response(url, "album")

    try:
        if error: raise KeyError
        images = response["image"]
    except (TypeError, KeyError): url = None
    else: url = get_image_url(images)

    try:
        if not url: raise IOError
        name = os.path.basename(image_base)
        images = [os.path.join(blaconst.COVERS, f) for f in
                os.listdir(blaconst.COVERS) if f.startswith(name)]
        map(os.unlink, images)
        cover, message = urllib.urlretrieve(
                url, "%s.%s" % (image_base, blautil.get_extension(url)))
    except IOError: pass

    return cover

def get_biography(track, image_base):
    image, biography = None, None

    url = "%s&method=artist.getinfo&artist=%s" % (
            blaconst.LASTFM_BASEURL, track[ARTIST])
    url = quote_url(url)
    error, response = get_response(url, "artist")

    try: images = response["image"]
    except (TypeError, KeyError): pass
    else:
        url = get_image_url(images)
        try:
            if not url: raise IOError
            image, message = urllib.urlretrieve(
                    url, "%s.%s" % (image_base, blautil.get_extension(url)))
        except IOError: pass

    try: biography = response["bio"]["content"]
    except (TypeError, KeyError): pass
    else:
        biography = blautil.remove_html_tags(
                biography.replace(LEGAL_NOTICE, "").strip())

    if error or response is None:
        print_d("Failed to retrieve artist biography: %s (error %d)"
                % (response, error))

    return image, biography

def get_events(limit, recommended, city="", country=""):
    events = None

    if recommended:
        session_key = BlaScrobbler.get_session_key()
        if not session_key: return events

        # since this is an authorized service the location information from the
        # associated last.fm user account is used. passing the country kwarg ,
        # doesn't allow specifying the city, so we just ignore it here
        method = "user.getRecommendedEvents"
        params = [
            ("method", method), ("api_key", blaconst.LASTFM_APIKEY),
            ("sk", session_key), ("limit", str(limit))
        ]

        api_signature = sign_api_call(params)
        params.append(("api_sig", api_signature))
        error, response = post_message(params)
        try: response = response["events"]
        except (TypeError, KeyError): pass

    else:
        location = ", ".join([city, country] if country else [city])
        url = "%s&method=geo.getEvents&location=%s&limit=%d" % (
                blaconst.LASTFM_BASEURL, location, limit)
        url = quote_url(url)
        error, response = get_response(url, "events")

    try:
        # if webservices are unavailable we might not get an error code despite
        # an erroneous return message
        if error: raise TypeError
        events = response["event"]
    except (TypeError, KeyError):
        print_d("Failed to retrieve recommended events: %s (error %d)"
                % (response, error))
    return events

def get_new_releases(recommended=False):
    releases = []
    user = blacfg.getstring("lastfm", "user")
    if not user: return releases

    url = "%s&method=user.getNewReleases&user=%s&userecs=%d" % (
            blaconst.LASTFM_BASEURL, user, int(recommended))
    url = quote_url(url)
    error, response = get_response(url, "albums")

    try:
        if error: raise TypeError
        releases = response["album"]
    except (TypeError, KeyError):
        print_d("Failed to get new releases: %s (error %d)"
                % (response, error))
    return releases

def get_request_token():
    url = "%s&method=auth.gettoken" % blaconst.LASTFM_BASEURL
    error, response = get_response(url, "token")
    if not error: token = response
    else:
        token = None
        print_d("Failed to retrieve request token: %s (error %d)"
                % (response, error))
    return token

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
    if not session_key: return

    method = "track.unlove" if unlove else "track.love"
    params = [
        ("method", method), ("api_key", blaconst.LASTFM_APIKEY),
        ("artist", track[ARTIST]), ("track", track[TITLE]),
        ("sk", session_key)
    ]

    # sign api call
    api_signature = sign_api_call(params)
    params.append(("api_sig", api_signature))
    error, response = post_message(params)
    if error:
        print_d("Failed to love/unlove song: %s (error %d)"
                % (response, error))


class BlaScrobbler(object):
    __requested_authorization = False
    __tid = -1
    __uri = None
    __start_time = 0
    __token = None
    __elapsed = 0
    __iterations = 0

    class SubmissionQueue(list):
        __items = []

        def __init__(self):
            super(BlaScrobbler.SubmissionQueue, self).__init__()
            self.__not_empty = threading.Condition(threading.Lock())
            self.__not_empty.acquire()
            self.__submitter()
            self.__restore()

        @blautil.thread
        def __submitter(self):
            while True:
                self.__not_empty.wait()

                items = []
                # the API allows submission of up to 50 scrobbles in one POST
                for idx in xrange(50):
                    try: items.append(self.__items[idx])
                    except IndexError: pass

                method = "track.scrobble"
                session_key = BlaScrobbler.get_session_key()
                if not session_key: continue
                params = [
                    ("method", method), ("api_key", blaconst.LASTFM_APIKEY),
                    ("sk", session_key)
                ]
                for idx, item in enumerate(items):
                    uri, start_time = item
                    try: track = library[uri]
                    except KeyError: continue
                    params.extend([
                        ("artist[%d]" % idx, track[ARTIST]),
                        ("track[%d]" % idx, track[TITLE]),
                        ("timestamp[%d]" % idx, str(start_time))
                    ])
                    if track[ALBUM]:
                        params.append(("album[%d]" % idx, track[ALBUM]))
                    if track[ALBUM_ARTIST]:
                        params.append(("album_artist[%d]" % idx,
                                track[ALBUM_ARTIST]))

                api_signature = sign_api_call(params)
                params.append(("api_sig", api_signature))
                error, response = post_message(params)
                if error:
                    print_d("Failed to submit %d scrobbles to "
                            "last.fm: %s (error %d)" % (len(item), response,
                            error)
                    )
                else: map(self.__items.remove, items)

        def __restore(self):
            items = blautil.deserialize_from_file(blaconst.SCROBBLES_PATH)
            if items:
                print_d("Queuing %d unsubmitted scrobble(s)"
                        % len(items))
                self.put(items)

        def put(self, items):
            self.__not_empty.acquire()
            self.__items.extend(items)
            self.__not_empty.notify()
            self.__not_empty.release()

        def save(self):
            blautil.serialize_to_file(self.__items, blaconst.SCROBBLES_PATH)

    def __init__(self):
        super(BlaScrobbler, self).__init__()
        blaplay.bla.register_for_cleanup(self)
        self.__queue = BlaScrobbler.SubmissionQueue()

    def __call__(self):
        self.__submit_last_track(True)

    @classmethod
    def __request_authorization(cls):
        from blaplay.blagui import blaguiutils
        if blaguiutils.question_dialog("last.fm authorization required",
                "In order to submit tracks to the last.fm scrobbler, blaplay "
                "needs to be authorized to use your account. Open the "
                "last.fm authorization page now?"):
            blautil.open_url("http://www.last.fm/api/auth/?api_key=%s&"
                    "token=%s" % (blaconst.LASTFM_APIKEY, cls.__token))
        return False

    def __passes_ignore(self, track):
        tokens = map(str.strip, filter(None, blacfg.getstring(
                "lastfm", "ignore.pattern").split(",")))
        res = [re.compile(t.decode("utf-8"), re.UNICODE | re.IGNORECASE)
                for t in tokens]
        for r in res:
            search = r.search
            for identifier in [ARTIST, TITLE]:
                if search(track[identifier]): return False
        return True

    @blautil.thread
    def __update_now_playing(self, delay=False):
        if delay: time.sleep(1)

        try: track = library[self.__uri]
        except KeyError: return
        if (not track[ARTIST] or not track[TITLE] or track[LENGTH] < 30 or
                not blacfg.getboolean("lastfm", "scrobble") or
                not blacfg.getboolean("lastfm", "nowplaying")):
            return

        session_key = self.get_session_key()
        if not session_key: return

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

        # sign api call
        api_signature = sign_api_call(params)
        params.append(("api_sig", api_signature))
        error, response = post_message(params)
        if error:
            print_d("Failed to update nowplaying: %s (error %d)"
                    % (response, error))

    def __query_status(self):
        state = player.get_state()
        self.__iterations += 1
        # wait 10~ seconds in between POSTs. before actually posting an update
        # kill any remaining thread that might be running
        if self.__iterations % 10 == 0:
            try: self.__t.kill()
            except AttributeError: pass
            self.__t = self.__update_now_playing()
            self.__iterations = 0

        if state == blaconst.STATE_PLAYING: self.__elapsed += 1
        return state != blaconst.STATE_STOPPED

    def __submit_last_track(self, shutdown=False):
        if self.__uri:
            try: track = library[self.__uri]
            except KeyError: return
            # according to the last.fm api docs, only tracks longer than 30
            # seconds should be submitted, and only if min(len[s]/2, 240)
            # seconds of the track elapsed. submission should happen when a
            # track stops, e.g. on track changes or playback stop (not pause)
            if (track[LENGTH] > 30 and track[ARTIST] and track[TITLE] and
                    blacfg.getboolean("lastfm", "scrobble") and
                    (self.__elapsed > track[LENGTH] / 2 or
                    self.__elapsed > 240)):
                print_d("Submitting track to scrobbler queue")
                self.__queue.put([(self.__uri, self.__start_time)])

        self.__uri = None
        if shutdown:
            print_i("Saving scrobbler queue")
            self.__queue.save()

    @classmethod
    def get_session_key(cls, create=False):
        session_key = blacfg.getstring("lastfm", "sessionkey")
        if session_key: return session_key
        if not create or cls.__requested_authorization: return None

        if not cls.__token:
            cls.__token = get_request_token()
            if not cls.__token: return None
            cls.__request_authorization()
            return None

        # FIXME: on start when there are unsubmitted scrobbles and no session
        #        key but a user name the request auth window will pop up which
        #        causes the statusbar to not update properly

        # TODO: check this more than once

        # we have a token, but it still might be unauthorized, i.e. we can't
        # create a session key from it. if that is the case, ignore the
        # situation until the next start of blaplay. in order to avoid sending
        # requests to last.fm all the time we set an escape variable when we
        # encounter an unauthorized token
        method = "auth.getSession"
        params = [
            ("method", method), ("api_key", blaconst.LASTFM_APIKEY),
            ("token", cls.__token)
        ]
        api_signature = sign_api_call(params)
        string = "&".join(["%s=%s" % p for p in params])
        url = "%s&api_sig=%s&%s" % (
                blaconst.LASTFM_BASEURL, api_signature, string)
        error, response = get_response(url, "session")
        if not error:
            session_key = response["key"]
            blacfg.set("lastfm", "sessionkey", session_key)
        else:
            session_key = None
            cls.__requested_authorization = True
        return session_key

    def submit_track(self, player):
        if (not blacfg.getstring("lastfm", "user") or
                not self.get_session_key(create=True)):
            return
        gobject.source_remove(self.__tid)

        # we request track submission on track changes. we don't have to check
        # here if a track passes the ignore settings as this is done when the
        # __uri attribute of the instance is set below
        self.__submit_last_track()

        self.__elapsed = 0
        self.__iterations = 0
        track = player.get_track()
        try:
            if player.radio: raise KeyError
            library[track.uri]
        except (AttributeError, KeyError): return

        if self.__passes_ignore(track):
            self.__uri = track.uri
            try: self.__t.kill()
            except AttributeError: pass
            self.__t = self.__update_now_playing(delay=True)
            self.__start_time = int(time.time())
            self.__tid = gobject.timeout_add(1000, self.__query_status)
        else:
            self.__uri = None
            print_d("Not submitting track \"%s - %s\" to the scrobbler queue"
                    % (track[ARTIST], track[TITLE]))

