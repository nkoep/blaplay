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
library = blaplay.bla.library
from blaplay.blacore import blacfg, blaconst
from blaplay import blagui
from blawindows import BlaUniqueWindow, BlaScrolledWindow
from blabrowsers import BlaBrowsers
import blaguiutils

ROW_SPACINGS = 3


class BlaPreferences(BlaUniqueWindow):
    class Page(gtk.VBox):
        def __init__(self, name):
            super(BlaPreferences.Page, self).__init__(spacing=ROW_SPACINGS)

            self.__name = name
            self.set_border_width(10)

        @property
        def name(self):
            return self.__name

    class GeneralSettings(Page):
        def __init__(self):
            super(BlaPreferences.GeneralSettings, self).__init__("General")

            options = [
                ("Cursor follows playback", "cursor.follows.playback",
                 self.__follow_playback),
                ("Remove tracks from queue after manual activation",
                 "queue.remove.when.activated", self.__queue_remove),
                ("Use timeout to perform search operations",
                 "search.after.timeout", self.__search_after_timeout)
            ]
            for label, key, callback in options:
                cb = gtk.CheckButton(label)
                cb.set_active(blacfg.getboolean("general", key))
                cb.connect("toggled", callback)
                self.pack_start(cb)

        def __follow_playback(self, checkbutton):
            blacfg.setboolean("general", "cursor.follows.playback",
                              checkbutton.get_active())

        def __queue_remove(self, checkbutton):
            blacfg.setboolean("general", "queue.remove.when.activated",
                              checkbutton.get_active())

        def __search_after_timeout(self, checkbutton):
            blacfg.setboolean("general", "search.after.timeout",
                              checkbutton.get_active())

    class TraySettings(Page):
        def __init__(self):
            super(BlaPreferences.TraySettings, self).__init__("Tray")

            def tray_changed(checkbutton, key):
                blacfg.setboolean("general", key, checkbutton.get_active())
            options = [
                ("Always display tray icon", "always.show.tray"),
                ("Close to tray", "close.to.tray"),
                ("Show tooltip", "tray.show.tooltip")
            ]
            for label, key in options:
                cb = gtk.CheckButton(label)
                cb.set_active(blacfg.getboolean("general", key))
                cb.connect("toggled", tray_changed, key)
                self.pack_start(cb)

    class LibrarySettings(Page):
        def __init__(self):
            super(BlaPreferences.LibrarySettings, self).__init__("Library")

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

            directories = blacfg.getdotliststr("library", "directories")
            for d in directories:
                model.append([d])

            table = gtk.Table(rows=2, columns=1)
            table.set_row_spacings(ROW_SPACINGS)
            items = [
                ("Add...", self.__add_directory),
                ("Remove", self.__remove_directory),
                ("Rescan all", self.__rescan_all)
            ]
            for idx, (label, callback) in enumerate(items):
                button = gtk.Button(label)
                button.connect("clicked", callback, treeview)
                table.attach(button, 0, 1, idx, idx+1)

            hbox.pack_start(viewport, expand=False)
            hbox.pack_start(table, expand=False)

            # Update library checkbutton
            cb = gtk.CheckButton("Update library on startup")
            cb.set_active(blacfg.getboolean("library", "update.on.startup"))
            cb.connect(
                "toggled",
                lambda cb: blacfg.setboolean("library", "update.on.startup",
                                             cb.get_active()))

            # Set up file restriction and exclusion options.
            def changed(entry, key):
                blacfg.set("library", key, entry.get_text())
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
                entry.set_text(blacfg.getstring("library", key))
                entry.connect("changed", changed, key)
                table.attach(entry, 1, 2, idx, idx+1, xoptions=gtk.FILL)

            self.pack_start(hbox, expand=False)
            self.pack_start(cb)
            self.pack_start(table)

        def __add_directory(self, button, treeview):
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
                directories = blacfg.getdotliststr("library", "directories")
                blacfg.set("library", "directories",
                           ":".join(directories + [directory]))
                if (os.path.realpath(directory) not in
                    map(os.path.realpath, directories)):
                    library.scan_directory(directory)

        def __remove_directory(self, button, treeview):
            model, iterator = treeview.get_selection().get_selected()

            if iterator:
                directories = blacfg.getdotliststr("library", "directories")
                directory = model[iterator][0]
                model.remove(iterator)

                try:
                    directories.remove(directory)
                except ValueError:
                    pass

                blacfg.set("library", "directories", ":".join(directories))
                if (os.path.realpath(directory) not in
                    map(os.path.realpath, directories)):
                    library.remove_directory(directory)

        def __rescan_all(self, button, treeview):
            for row in treeview.get_model():
                library.scan_directory(row[0])

    class BrowserSettings(Page):
        def __init__(self):
            super(BlaPreferences.BrowserSettings, self).__init__("Browsers")

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
                blacfg.set("library", "%s.action" % key, action)
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
                cb.set_active(blacfg.getint("library", "%s.action" % key))
                cb.connect("changed", changed, key)
                table.attach(cb, 1, 2, idx, idx+1, xoptions=gtk.FILL)

            cb = gtk.CheckButton("Use custom treeview as library browser")
            cb.set_active(blacfg.getboolean("library", "custom.browser"))
            def toggled(cb):
                blacfg.setboolean("library", "custom.browser", cb.get_active())
            cb.connect("toggled", toggled)

            self.pack_start(table)
            self.pack_start(cb)

    class PlayerSettings(Page):
        def __init__(self):
            super(BlaPreferences.PlayerSettings, self).__init__("Player")

            logarithmic_volume_scale = gtk.CheckButton(
                "Use logarithmic volume scale")
            logarithmic_volume_scale.set_active(
                blacfg.getboolean("player", "logarithmic.volume.scale"))
            logarithmic_volume_scale.connect(
                "toggled", self.__volume_scale_changed)

            state = blacfg.getboolean("player", "use.equalizer")
            self.__scales = []

            use_equalizer = gtk.CheckButton("Use equalizer")
            use_equalizer.set_active(state)
            use_equalizer.connect("toggled", self.__use_equalizer_changed)

            self.__profile_box = gtk.combo_box_new_text()
            self.__profile_box.set_size_request(250, -1)
            self.__profile_box.connect("changed", self.__profile_changed)

            old_profile = blacfg.getstring("player", "equalizer.profile")
            profiles = blacfg.get_keys("equalizer.profiles")

            for idx, profile in enumerate(profiles):
                self.__profile_box.append_text(profile[0])
                if profile[0] == old_profile:
                    self.__profile_box.set_active(idx)

            button_table = gtk.Table(rows=1, columns=3, homogeneous=True)
            new_profile_button = gtk.Button("New")
            new_profile_button.connect(
                "clicked", self.__new_profile, self.__profile_box)
            delete_profile_button = gtk.Button("Delete")
            delete_profile_button.connect(
                "clicked", self.__delete_profile, self.__profile_box)
            reset_profile_button = gtk.Button("Reset")
            reset_profile_button.connect_object(
                "clicked", BlaPreferences.PlayerSettings.__reset_profile, self)
            button_table.attach(new_profile_button, 0, 1, 0, 1, xpadding=2)
            button_table.attach(delete_profile_button, 1, 2, 0, 1, xpadding=2)
            button_table.attach(reset_profile_button, 2, 3, 0, 1, xpadding=2)

            button_box = gtk.HBox()
            button_box.pack_start(
                gtk.Label("Profile:"), expand=False, padding=10)
            button_box.pack_start(self.__profile_box, expand=False)
            button_box.pack_start(button_table, expand=False, padding=16)

            table = gtk.Table(rows=2, columns=1, homogeneous=False)
            table.set_row_spacings(ROW_SPACINGS)
            table.attach(logarithmic_volume_scale, 0, 2, 0, 1, xpadding=2)
            table.attach(use_equalizer, 0, 1, 1, 2, xpadding=2)

            self.__scale_container = gtk.Table(
                rows=1, columns=blaconst.EQUALIZER_BANDS)
            self.__scale_container.set_size_request(500, 200)

            def format_value(scale, value):
                sign = "+" if value >= 0 else "-"
                return "%s%.1f dB" % (sign, abs(value))
            # XXX: The cut-off frequencies shouldn't be hard-coded!
            bands = [29, 59, 119, 237, 474, 947, 1889, 3770, 7523, 15011]
            values = blacfg.getlistfloat("equalizer.profiles", old_profile)
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
                scale.connect("value_changed", self.__equalizer_value_changed,
                              idx)
                scale.connect("format_value", format_value)
                self.__scales.append(scale)
                vbox.pack_start(scale)

                self.__scale_container.attach(vbox, idx, idx+1, 0, 1,
                                        xoptions=gtk.FILL, xpadding=15)

            self.pack_start(table)
            self.pack_start(button_box)
            self.pack_start(self.__scale_container, expand=False, padding=10)

            self.__use_equalizer_changed(use_equalizer)

        def __volume_scale_changed(self, checkbutton):
            blacfg.setboolean("player", "logarithmic.volume.scale",
                              checkbutton.get_active())
            player.set_volume(blacfg.getfloat("player", "volume") * 100)

        def __use_equalizer_changed(self, checkbutton):
            state = checkbutton.get_active()
            blacfg.setboolean("player", "use.equalizer", state)
            player.enable_equalizer(state)

            if state and not self.__profile_box.get_model().get_iter_first():
                self.__scale_container.set_sensitive(False)
            else:
                self.__scale_container.set_sensitive(state)

        def __reset_profile(self):
            for scale in self.__scales:
                scale.set_value(0)

        def __equalizer_value_changed(self, scale, band):
            profile_name = self.__profile_box.get_active_text()
            if not profile_name:
                return

            # Store new equalizer values in config.
            values = []
            for s in self.__scales:
                values.append(s.get_value())
            values[band] = scale.get_value()

            blacfg.set("equalizer.profiles", profile_name,
                       ("%.1f, " * (blaconst.EQUALIZER_BANDS-1) + "%.1f") %
                       tuple(values))
            blacfg.set("player", "equalizer.profile", profile_name)

            # Update the specified band in the playback device.
            player.set_equalizer_value(band, scale.get_value())

        def __profile_changed(self, combobox):
            profile_name = combobox.get_active_text()
            if profile_name:
                values = blacfg.getlistfloat(
                    "equalizer.profiles", profile_name)
                blacfg.set("player", "equalizer.profile", profile_name)

                if not values:
                    values = [0.0] * blaconst.EQUALIZER_BANDS
                    blacfg.set(
                        "equalizer.profiles", profile_name,
                        ("%.1f, " * (blaconst.EQUALIZER_BANDS-1) + "%.1f") %
                        tuple(values))

                for idx, s in enumerate(self.__scales):
                    s.set_value(values[idx])
            else:
                blacfg.set("player", "equalizer.profile", "")
                for s in self.__scales:
                    s.set_value(0)
                self.__scale_container.set_sensitive(False)

            player.enable_equalizer(True)

        def __new_profile(self, button, combobox):
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
                if blacfg.has_option("equalizer.profiles",  profile_name):
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
                    self.__reset_profile()

                else:
                    combobox.prepend_text(profile_name)
                    combobox.set_active(0)

                self.__scale_container.set_sensitive(True)

        def __delete_profile(self, button, combobox):
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
                blacfg.delete_option("equalizer.profiles", profile_name)

    class Keybindings(Page):
        def __init__(self):
            super(BlaPreferences.Keybindings, self).__init__(
                "Global keybindings")

            from blakeys import BlaKeys
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
                accel = blacfg.getstring("keybindings", action)
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
                blacfg.set("keybindings", action, accel)

            def cleared(renderer, path):
                bindings.set_value(bindings.get_iter(path), 1, None)
                action = actions[int(path)][-1]
                blakeys.unbind(blacfg.getstring("keybindings", action))
                blacfg.set("keybindings", action, "")

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

    class LastfmSettings(Page):
        def __init__(self):
            super(BlaPreferences.LastfmSettings, self).__init__("last.fm")

            scrobble = gtk.CheckButton("Enable scrobbling")
            scrobble.set_active(blacfg.getboolean("lastfm", "scrobble"))
            scrobble.connect("toggled", self.__scrobble_changed)

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
                entry.set_text(blacfg.getstring("lastfm", key))
                entry.set_tooltip_text(tooltip)
                entry.connect("changed", self.__entry_changed, key)
                table.attach(entry, 1, 2, idx, idx+1, xoptions=gtk.FILL)

            nowplaying = gtk.CheckButton("Send \"now playing\" messages")
            nowplaying.set_active(blacfg.getboolean("lastfm", "now.playing"))
            nowplaying.connect("toggled", self.__nowplaying_changed)

            self.pack_start(scrobble, expand=False)
            self.pack_start(table, expand=False)
            self.pack_start(nowplaying, expand=False)

        def __entry_changed(self, entry, key):
            blacfg.set("lastfm", key, entry.get_text())

        def __scrobble_changed(self, checkbutton):
            blacfg.setboolean("lastfm", "scrobble", checkbutton.get_active())

        def __nowplaying_changed(self, checkbutton):
            blacfg.setboolean("lastfm", "now.playing",
                              checkbutton.get_active())

    def __init__(self, *args):
        super(BlaPreferences, self).__init__()
        self.set_title("Preferences")

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
        vbox.set_border_width(10)
        for cls in [self.GeneralSettings, self.TraySettings,
                    self.LibrarySettings, self.BrowserSettings,
                    self.PlayerSettings, self.Keybindings,
                    self.LastfmSettings]:
            section = Section(cls())
            vbox.pack_start(section)

        sw = BlaScrolledWindow()
        sw.set_shadow_type(gtk.SHADOW_NONE)
        sw.add_with_viewport(vbox)
        self.vbox.pack_start(sw)
        self.set_size_request(1000, 750)
        self.show_all()

