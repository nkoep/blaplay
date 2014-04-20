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

import gobject
import gtk

import blaplay
player = blaplay.bla.player
from blaplay.blacore import blaconst
from ..blakeys import BlaKeys
from .. import blaguiutils
from .blaview import BlaView

ROW_SPACINGS = 3


class _Page(gtk.VBox):
    def __init__(self, name, config, library):
        super(_Page, self).__init__(spacing=ROW_SPACINGS)
        self.set_border_width(10)

        self._name = name
        self._config = config
        self._library = library

    @property
    def name(self):
        return self._name

class _GeneralSettings(_Page):
    def __init__(self, *args, **kwargs):
        super(_GeneralSettings, self).__init__("General", *args, **kwargs)

        def on_toggled(checkbutton, key):
            self._config.setboolean("general", key, checkbutton.get_active())
        options = [
            ("Display audio spectrum", "show.visualization"),
            ("Cursor follows playback", "cursor.follows.playback"),
            ("Remove tracks from queue after manual activation",
             "queue.remove.when.activated"),
            ("Use timeout to perform search operations",
             "search.after.timeout")
        ]
        for label, key in options:
            cb = gtk.CheckButton(label)
            cb.set_active(self._config.getboolean("general", key))
            cb.connect("toggled", on_toggled, key)
            self.pack_start(cb)

class _TraySettings(_Page):
    def __init__(self, *args, **kwargs):
        super(_TraySettings, self).__init__("Tray", *args, **kwargs)

        def tray_changed(checkbutton, key):
            self._config.setboolean("general", key, checkbutton.get_active())
        options = [
            ("Always display tray icon", "always.show.tray"),
            ("Close to tray", "close.to.tray")
        ]
        for label, key in options:
            cb = gtk.CheckButton(label)
            cb.set_active(self._config.getboolean("general", key))
            cb.connect("toggled", tray_changed, key)
            self.pack_start(cb)

class _LibrarySettings(_Page):
    def __init__(self, *args, **kwargs):
        super(_LibrarySettings, self).__init__("Library", *args, **kwargs)

        hbox = gtk.HBox(spacing=ROW_SPACINGS)

        # Set up the directory selector.
        model = gtk.ListStore(gobject.TYPE_STRING)
        treeview = gtk.TreeView(model)
        treeview.set_size_request(500, -1)
        treeview.set_property("rules_hint", True)
        treeview.insert_column_with_attributes(
            -1, "Directories", gtk.CellRendererText(), text=0)

        viewport = gtk.Viewport()
        viewport.set_shadow_type(gtk.SHADOW_IN)
        viewport.add(treeview)

        directories = self._config.getdotliststr("library", "directories")
        for d in directories:
            model.append([d])

        table = gtk.Table(rows=2, columns=1)
        table.set_row_spacings(ROW_SPACINGS)
        items = [
            ("Add...", self._add_directory),
            ("Remove", self._remove_directory),
            ("Rescan all", self._rescan_all)
        ]
        for idx, (label, callback) in enumerate(items):
            button = gtk.Button(label)
            button.connect("clicked", callback, treeview)
            table.attach(button, 0, 1, idx, idx+1)

        hbox.pack_start(viewport, expand=False)
        hbox.pack_start(table, expand=False)

        # Update library checkbutton
        cb = gtk.CheckButton("Update library on startup")
        cb.set_active(self._config.getboolean("library", "update.on.startup"))
        cb.connect(
            "toggled",
            lambda cb: self._config.setboolean("library", "update.on.startup",
                                         cb.get_active()))

        # Set up file restriction and exclusion options.
        def changed(entry, key):
            self._config.set_("library", key, entry.get_text())
        options = [
            ("Restrict to", "Comma-separated list, works on filenames",
             "restrict.to"),
            ("Exclude", "Comma-separated list, works on filenames",
             "exclude")
        ]
        table = gtk.Table(rows=len(options), columns=2, homogeneous=False)
        table.set_row_spacings(ROW_SPACINGS)
        for idx, (label, tooltip, key) in enumerate(options):
            # Add the label.
            label = gtk.Label("%s:" % label)
            label.set_alignment(xalign=0.0, yalign=0.5)
            table.attach(label, 0, 1, idx, idx+1, xoptions=gtk.FILL,
                         xpadding=5)

            # Add the input field.
            entry = gtk.Entry()
            entry.set_size_request(250, -1)
            entry.set_tooltip_text(tooltip)
            entry.set_text(self._config.getstring("library", key))
            entry.connect("changed", changed, key)
            table.attach(entry, 1, 2, idx, idx+1, xoptions=gtk.FILL)

        self.pack_start(hbox, expand=False)
        self.pack_start(cb)
        self.pack_start(table)

    def _add_directory(self, button, treeview):
        filediag = gtk.FileChooserDialog(
            "Select a directory",
            action=gtk.FILE_CHOOSER_ACTION_SELECT_FOLDER,
            buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                     gtk.STOCK_OPEN, gtk.RESPONSE_OK))
            # TODO: Remember the last directory.
        filediag.set_current_folder(os.path.expanduser("~"))
        response = filediag.run()
        directory = None

        if response == gtk.RESPONSE_OK:
            directory = filediag.get_filename()
        filediag.destroy()

        if directory:
            model = treeview.get_model()
            for row in model:
                if row[0] == directory:
                    return

            model.append([directory])
            directories = self._config.getdotliststr("library", "directories")
            self._config.set_("library", "directories",
                        ":".join(directories + [directory]))
            if (os.path.realpath(directory) not in
                map(os.path.realpath, directories)):
                self._library.scan_directory(directory)

    def _remove_directory(self, button, treeview):
        model, iterator = treeview.get_selection().get_selected()

        if iterator:
            directories = self._config.getdotliststr("library", "directories")
            directory = model[iterator][0]
            model.remove(iterator)

            try:
                directories.remove(directory)
            except ValueError:
                pass

            self._config.set_("library", "directories", ":".join(directories))
            if (os.path.realpath(directory) not in
                map(os.path.realpath, directories)):
                self._library.remove_directory(directory)

    def _rescan_all(self, button, treeview):
        for row in treeview.get_model():
            self._library.scan_directory(row[0])

class _BrowserSettings(_Page):
    def __init__(self, *args, **kwargs):
        super(_BrowserSettings, self).__init__("Browsers", *args, **kwargs)

        # TODO: Move the key and button configuration to a model dialog so
        #       the comboboxes don't interfere with page scroll events.
        # Add the action selectors.
        from collections import OrderedDict
        actions = OrderedDict([
            ("send to current playlist", blaconst.ACTION_SEND_TO_CURRENT),
            ("add to current playlist", blaconst.ACTION_ADD_TO_CURRENT),
            ("send to new playlist", blaconst.ACTION_SEND_TO_NEW),
            ("expand/collapse", blaconst.ACTION_EXPAND_COLLAPSE)
        ])
        def changed(combobox, key):
            action = actions[combobox.get_active_text()]
            self._config.set_("library", "%s.action" % key, action)
        options = [("Double-click", "doubleclick"),
                   ("Middle-click", "middleclick"), ("Return", "return")]
        table = gtk.Table(rows=len(options), columns=2, homogeneous=False)
        table.set_row_spacings(ROW_SPACINGS)
        for idx, (label, key) in enumerate(options):
            # Add the label.
            label = gtk.Label("%s:" % label)
            label.set_alignment(xalign=0.0, yalign=0.5)
            table.attach(label, 0, 1, idx, idx+1, xoptions=gtk.FILL,
                         xpadding=5)

            # FIXME: These occasionally grab focus while scrolling. It's
            #        probably best to add these to a modal window instead.
            #        The same goes for the scales in the equalizer section.
            # Add the combobox.
            cb = gtk.combo_box_new_text()
            cb.set_size_request(250, -1)
            map(cb.append_text, actions.keys())
            cb.set_active(self._config.getint("library", "%s.action" % key))
            cb.connect("changed", changed, key)
            table.attach(cb, 1, 2, idx, idx+1, xoptions=gtk.FILL)

        cb = gtk.CheckButton("Use custom treeview as library browser")
        cb.set_active(self._config.getboolean("library", "custom.browser"))
        def toggled(cb):
            self._config.setboolean("library", "custom.browser",
                                    cb.get_active())
        cb.connect("toggled", toggled)

        self.pack_start(table)
        self.pack_start(cb)

class _PlayerSettings(_Page):
    def __init__(self, *args, **kwargs):
        super(_PlayerSettings, self).__init__("Player", *args, **kwargs)

        logarithmic_volume_scale = gtk.CheckButton(
            "Use logarithmic volume scale")
        logarithmic_volume_scale.set_active(
            self._config.getboolean("player", "logarithmic.volume.scale"))
        logarithmic_volume_scale.connect(
            "toggled", self._volume_scale_changed)

        state = self._config.getboolean("player", "use.equalizer")
        self._scales = []

        use_equalizer = gtk.CheckButton("Use equalizer")
        use_equalizer.set_active(state)
        use_equalizer.connect("toggled", self._use_equalizer_changed)

        self._profile_box = gtk.combo_box_new_text()
        self._profile_box.set_size_request(250, -1)
        self._profile_box.connect("changed", self._profile_changed)

        old_profile = self._config.getstring("player", "equalizer.profile")
        profiles = self._config.get_keys("equalizer.profiles")

        for idx, profile in enumerate(profiles):
            self._profile_box.append_text(profile[0])
            if profile[0] == old_profile:
                self._profile_box.set_active(idx)

        button_table = gtk.Table(rows=1, columns=3, homogeneous=True)
        new_profile_button = gtk.Button("New")
        new_profile_button.connect(
            "clicked", self._new_profile, self._profile_box)
        delete_profile_button = gtk.Button("Delete")
        delete_profile_button.connect(
            "clicked", self._delete_profile, self._profile_box)
        reset_profile_button = gtk.Button("Reset")
        reset_profile_button.connect_object(
            "clicked", _PlayerSettings._reset_profile, self)
        button_table.attach(new_profile_button, 0, 1, 0, 1, xpadding=2)
        button_table.attach(delete_profile_button, 1, 2, 0, 1, xpadding=2)
        button_table.attach(reset_profile_button, 2, 3, 0, 1, xpadding=2)

        button_box = gtk.HBox()
        button_box.pack_start(
            gtk.Label("Profile:"), expand=False, padding=10)
        button_box.pack_start(self._profile_box, expand=False)
        button_box.pack_start(button_table, expand=False, padding=16)

        table = gtk.Table(rows=2, columns=1, homogeneous=False)
        table.set_row_spacings(ROW_SPACINGS)
        table.attach(logarithmic_volume_scale, 0, 2, 0, 1, xpadding=2)
        table.attach(use_equalizer, 0, 1, 1, 2, xpadding=2)

        self._scale_container = gtk.Table(
            rows=1, columns=blaconst.EQUALIZER_BANDS)
        self._scale_container.set_size_request(500, 200)

        def format_value(scale, value):
            sign = "+" if value >= 0 else "-"
            return "%s%.1f dB" % (sign, abs(value))
        # XXX: The cut-off frequencies shouldn't be hard-coded!
        bands = [29, 59, 119, 237, 474, 947, 1889, 3770, 7523, 15011]
        values = self._config.getlistfloat("equalizer.profiles", old_profile)
        if not values:
            values = [0] * blaconst.EQUALIZER_BANDS
        for idx, val in enumerate(values):
            vbox = gtk.VBox(spacing=10)
            label = gtk.Label("%d Hz" % bands[idx])
            vbox.pack_start(label, expand=False)

            scale = gtk.VScale(gtk.Adjustment(val, -24., 12., 0.1))
            scale.set_inverted(True)
            scale.set_update_policy(gtk.UPDATE_DISCONTINUOUS)
            scale.set_value(values[idx])
            scale.set_digits(1)
            scale.set_draw_value(True)
            scale.set_value_pos(gtk.POS_BOTTOM)
            scale.connect("value_changed", self._equalizer_value_changed,
                          idx)
            scale.connect("format_value", format_value)
            self._scales.append(scale)
            vbox.pack_start(scale)

            self._scale_container.attach(vbox, idx, idx+1, 0, 1,
                                         xoptions=gtk.FILL, xpadding=15)

        self.pack_start(table)
        self.pack_start(button_box)
        self.pack_start(self._scale_container, expand=False, padding=10)

        self._use_equalizer_changed(use_equalizer)

    def _volume_scale_changed(self, checkbutton):
        self._config.setboolean("player", "logarithmic.volume.scale",
                          checkbutton.get_active())
        player.set_volume(self._config.getfloat("player", "volume") * 100)

    def _use_equalizer_changed(self, checkbutton):
        state = checkbutton.get_active()
        self._config.setboolean("player", "use.equalizer", state)
        player.enable_equalizer(state)

        if state and not self._profile_box.get_model().get_iter_first():
            self._scale_container.set_sensitive(False)
        else:
            self._scale_container.set_sensitive(state)

    def _reset_profile(self):
        for scale in self._scales:
            scale.set_value(0)

    def _equalizer_value_changed(self, scale, band):
        profile_name = self._profile_box.get_active_text()
        if not profile_name:
            return

        # Store new equalizer values in config.
        values = []
        for s in self._scales:
            values.append(s.get_value())
        values[band] = scale.get_value()

        self._config.set_("equalizer.profiles", profile_name,
                    ("%.1f, " * (blaconst.EQUALIZER_BANDS-1) + "%.1f") %
                    tuple(values))
        self._config.set_("player", "equalizer.profile", profile_name)

        # Update the specified band in the playback device.
        player.set_equalizer_value(band, scale.get_value())

    def _profile_changed(self, combobox):
        profile_name = combobox.get_active_text()
        if profile_name:
            values = self._config.getlistfloat(
                "equalizer.profiles", profile_name)
            self._config.set_("player", "equalizer.profile", profile_name)

            if not values:
                values = [0.0] * blaconst.EQUALIZER_BANDS
                self._config.set_(
                    "equalizer.profiles", profile_name,
                    ("%.1f, " * (blaconst.EQUALIZER_BANDS-1) + "%.1f") %
                    tuple(values))

            for idx, s in enumerate(self._scales):
                s.set_value(values[idx])
        else:
            self._config.set_("player", "equalizer.profile", "")
            for s in self._scales:
                s.set_value(0)
            self._scale_container.set_sensitive(False)

        player.enable_equalizer(True)

    def _new_profile(self, button, combobox):
        diag = blaguiutils.BlaDialog(parent=self.get_toplevel(),
                                     title="New EQ profile")
        vbox = gtk.VBox(spacing=5)
        vbox.set_border_width(10)
        entry = gtk.Entry()
        entry.connect(
            "activate", lambda *x: diag.response(gtk.RESPONSE_OK))
        label = gtk.Label("Profile name:")
        label.set_alignment(xalign=0.0, yalign=0.5)
        vbox.pack_start(label)
        vbox.pack_start(entry)
        diag.vbox.pack_start(vbox)
        diag.show_all()
        response = diag.run()
        profile_name = entry.get_text()
        diag.destroy()

        if response == gtk.RESPONSE_OK and profile_name:
            if self._config.has_option("equalizer.profiles",  profile_name):
                diag = blaguiutils.BlaDialog(
                    parent=self.get_toplevel(), title="Profile exists!",
                    buttons=(gtk.STOCK_NO, gtk.RESPONSE_NO,
                             gtk.STOCK_YES, gtk.RESPONSE_YES))
                diag.vbox.pack_start(gtk.Label("Overwrite profile?"))
                diag.show_all()
                response = diag.run()
                diag.destroy()

                if response == gtk.RESPONSE_NO:
                    return
                self._reset_profile()

            else:
                combobox.prepend_text(profile_name)
                combobox.set_active(0)

            self._scale_container.set_sensitive(True)

    def _delete_profile(self, button, combobox):
        model = combobox.get_model()
        iterator = model.get_iter_first()

        if iterator:
            profile_index = combobox.get_active()
            profile_name = combobox.get_active_text()

            count = 1
            while iterator:
                iterator = model.iter_next(iterator)
                count += 1

            if count > 1:
                if profile_index != 0:
                    combobox.set_active(0)
                else:
                    combobox.set_active(1)

            combobox.remove_text(profile_index)
            self._config.delete_option("equalizer.profiles", profile_name)

class _Keybindings(_Page):
    def __init__(self, *args, **kwargs):
        super(_Keybindings, self).__init__(
            "Global keybindings", *args, **kwargs)

        blakeys = BlaKeys()
        actions = [
            ("Play/Pause", "playpause"),
            ("Pause", "pause"),
            ("Stop", "stop"),
            ("Previous track", "previous"),
            ("Next track", "next"),
            ("Volume up", "volup"),
            ("Volume down", "voldown"),
            ("Mute", "mute")
        ]
        bindings = gtk.ListStore(gobject.TYPE_STRING, gobject.TYPE_STRING)
        for label, action in actions:
            accel = self._config.getstring("keybindings", action)
            bindings.append([label, accel])

        treeview = gtk.TreeView()
        treeview.set_size_request(250, -1)
        treeview.set_property("rules_hint", True)
        treeview.insert_column_with_attributes(
            -1, "Action", gtk.CellRendererText(), text=0)

        def edited(renderer, path, key, mod, *args):
            action = actions[int(path)][-1]
            accel = gtk.accelerator_name(key, mod)
            blakeys.bind(action, accel)
            bindings.set_value(bindings.get_iter(path), 1, accel)
            self._config.set_("keybindings", action, accel)

        def cleared(renderer, path):
            bindings.set_value(bindings.get_iter(path), 1, None)
            action = actions[int(path)][-1]
            blakeys.unbind(self._config.getstring("keybindings", action))
            self._config.set_("keybindings", action, "")

        renderer = gtk.CellRendererAccel()
        renderer.set_property("editable", True)
        renderer.connect("accel_edited", edited)
        renderer.connect("accel_cleared", cleared)
        treeview.insert_column_with_attributes(
            -1, "Binding", renderer, text=1)
        treeview.set_model(bindings)

        viewport = gtk.Viewport()
        viewport.set_shadow_type(gtk.SHADOW_IN)
        viewport.add(treeview)
        hbox = gtk.HBox()
        hbox.pack_start(viewport, expand=False)
        self.pack_start(hbox, expand=False)
        if not blakeys.can_bind():
            label = gtk.Label()
            label.set_markup(
                "<b>Note</b>: The <i>keybinder</i> module is not "
                "available on your system. As a result, global "
                "keybindings will currently have no effect.")
            self.pack_start(label, expand=False, padding=20)

class _LastfmSettings(_Page):
    def __init__(self, *args, **kwargs):
        super(_LastfmSettings, self).__init__("last.fm", *args, **kwargs)

        scrobble = gtk.CheckButton("Enable scrobbling")
        scrobble.set_active(self._config.getboolean("lastfm", "scrobble"))
        scrobble.connect("toggled", self._scrobble_changed)

        options = [
            ("Username", "user", ""),
            ("Ignore pattern", "ignore.pattern", "Comma-separated list")
        ]
        table = gtk.Table(rows=len(options), columns=2, homogeneous=False)
        table.set_row_spacings(ROW_SPACINGS)
        for idx, (label, key, tooltip) in enumerate(options):
            # Add the label.
            label = gtk.Label("%s:" % label)
            label.set_alignment(xalign=0.0, yalign=0.5)
            table.attach(label, 0, 1, idx, idx+1, xoptions=gtk.FILL,
                         xpadding=5)

            # Add the input field.
            entry = gtk.Entry()
            entry.set_size_request(250, -1)
            entry.set_text(self._config.getstring("lastfm", key))
            entry.set_tooltip_text(tooltip)
            entry.connect("changed", self._entry_changed, key)
            table.attach(entry, 1, 2, idx, idx+1, xoptions=gtk.FILL)

        nowplaying = gtk.CheckButton("Send \"now playing\" messages")
        nowplaying.set_active(self._config.getboolean("lastfm", "now.playing"))
        nowplaying.connect("toggled", self._nowplaying_changed)

        self.pack_start(scrobble, expand=False)
        self.pack_start(table, expand=False)
        self.pack_start(nowplaying, expand=False)

    def _entry_changed(self, entry, key):
        self._config.set_("lastfm", key, entry.get_text())

    def _scrobble_changed(self, checkbutton):
        self._config.setboolean("lastfm", "scrobble", checkbutton.get_active())

    def _nowplaying_changed(self, checkbutton):
        self._config.setboolean("lastfm", "now.playing",
                          checkbutton.get_active())

class BlaPreferences(BlaView):
    ID = blaconst.VIEW_PREFERENCES

    def __init__(self, config, library, *args, **kwargs):
        super(BlaPreferences, self).__init__("Preferences", *args, **kwargs)
        self._header.set_icon_from_stock(gtk.STOCK_PREFERENCES)

        class Section(gtk.VBox):
            def __init__(self, page):
                super(Section, self).__init__()
                label = gtk.Label()
                label.set_markup("<b>%s</b>" % page.name)
                alignment = gtk.Alignment(xalign=0.0, yalign=0.5)
                alignment.add(label)
                self.pack_start(alignment)
                self.pack_start(page)

        vbox = gtk.VBox(spacing=5)
        vbox.set_border_width(25)
        for page in [_GeneralSettings, _TraySettings, _LibrarySettings,
                     _BrowserSettings, _PlayerSettings, _Keybindings,
                     _LastfmSettings]:
            section = Section(page(config, library))
            vbox.pack_start(section)

        self.add(blaguiutils.wrap_in_viewport(vbox))
        self.show_all()

