# TODO

## v0.2
- Add acoustid support
- Add (proper) video support
- Add compact interface
- Add musicbrainz-ngs support (mainly for the lyrics (wikia) and cover
  (coverartarchive.org) fetchers)
- Add support for parsing CUE sheets
- Implement gapless playback
- Finish MPRIS2 implementation
- Get covers from covertartarchive/musicbrainz if they're not on last.fm
- Implement shuffle albums/repeat album playback modes
- Implement peeking (tooltips for previous/next/random buttons showing which
  track would be played if button was clicked)
- Parse tags from filename/rename files from tags
- Write up some crude unit tests to harden core functionality
- Test if it's feasible to drop the mutagen dependency in favor of
  GstDiscoverer/GstTagSetter
- Add customizable paned view to playlists
- Integrate radio streams into regular playlists
- Replace radio streams view with a history view

## v0.3+
- Restore closed playlists
- Lower memory footprint
- Improve startup speed/reduce import overhead
- Port to GI once stability/performance is satisfying
- Port to py3k once all dependencies are ported (the main hold-up being
  mutagen)
- Design a crude plugin system
- Loosen integration of last.fm services and move its functionality into
  appropriate plugins

