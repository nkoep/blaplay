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
from blavisualization import BlaVisualization
import blaguiutils


class BlaPreferences(BlaUniqueWindow):
    class Page(gtk.VBox):
        def __init__(self, name):
            super(BlaPreferences.Page, self).__init__(spacing=10)

            self.__name = name
            self.set_border_width(10)

        @property
        def name(self):
            return self.__name

    class GeneralSettings(Page):
        def __init__(self):
            super(BlaPreferences.GeneralSettings, self).__init__("General")

            # Tray
            tray_frame = gtk.Frame("Tray")
            tray_table = gtk.Table(rows=2, columns=2, homogeneous=False)
            tray_table.set_border_width(10)
            tray_frame.add(tray_table)

            options = [
                ("Always display tray icon", "always.show.tray", True,
                 [0, 1, 0, 1]),
                ("Close to tray", "close.to.tray", False, [0, 1, 1, 2]),
                ("Show tooltip", "tray.tooltip", False, [1, 2, 0, 1])
            ]

            for label, key, update_visibility, coords in options:
                b = gtk.CheckButton(label)
                b.set_active(blacfg.getboolean("general", key))
                b.connect("toggled", self.__tray_changed, key,
                          update_visibility)
                tray_table.attach(b, *coords)

            # Miscellaneous
            misc_frame = gtk.Frame("Miscellaneous")
            misc_table = gtk.Table(rows=1, columns=2, homogeneous=False)
            misc_table.set_border_width(10)
            misc_frame.add(misc_table)

            cb = gtk.CheckButton("Cursor follows playback")
            cb.set_active(
                blacfg.getboolean("general", "cursor.follows.playback"))
            cb.connect("toggled", self.__follow_playback)
            misc_table.attach(cb, 0, 1, 0, 1)

            cb = gtk.CheckButton(
                "Remove track from queue on double-click or return")
            cb.set_active(blacfg.getboolean(
                "general", "queue.remove.when.activated"))
            cb.connect("toggled", self.__queue_remove)
            misc_table.attach(cb, 1, 2, 0, 1, xpadding=10)

            cb = gtk.CheckButton("Search after timeout")
            cb.set_active(
                blacfg.getboolean("general", "search.after.timeout"))
            cb.connect("toggled", self.__search_after_timeout)
            misc_table.attach(cb, 0, 2, 1, 2)

            self.pack_start(tray_frame, expand=False)
            self.pack_start(misc_frame, expand=False)

        def __tray_changed(self, checkbutton, key, update_visibility):
            state = checkbutton.get_active()
            if update_visibility:
                blagui.tray.set_visible(state)
            blacfg.setboolean("general", key, state)
            if key == "tray.tooltip":
                blagui.tray.set_has_tooltip(state)

        def __follow_playback(self, checkbutton):
            blacfg.setboolean("general", "cursor.follows.playback",
                              checkbutton.get_active())

        def __queue_remove(self, checkbutton):
            blacfg.setboolean("general", "queue.remove.when.activated",
                              checkbutton.get_active())

        def __search_after_timeout(self, checkbutton):
            blacfg.setboolean("general", "search.after.timeout",
                              checkbutton.get_active())

    class LibraryBrowsersSettings(Page):
        def __init__(self):
            super(BlaPreferences.LibraryBrowsersSettings, self).__init__(
                "Library/Browsers")

            restrict_string = blacfg.getstring("library", "restrict.to")
            exclude_string = blacfg.getstring("library", "exclude")
            def destroy(*args):
                if (restrict_string !=
                    blacfg.getstring("library", "restrict.to") or
                    exclude_string != blacfg.getstring("library", "exclude")):
                    gobject.timeout_add(500, library.update_library)
            self.connect("destroy", destroy)

            hbox = gtk.HBox(spacing=10)

            model = gtk.ListStore(gobject.TYPE_STRING)
            treeview = gtk.TreeView(model)
            treeview.set_property("rules_hint", True)
            r = gtk.CellRendererText()
            treeview.insert_column_with_attributes(
                -1, "Directories", r, text=0)

            sw = BlaScrolledWindow()
            sw.set_shadow_type(gtk.SHADOW_IN)
            sw.set_size_request(-1, 140)
            sw.add(treeview)

            directories = blacfg.getdotliststr("library", "directories")
            for f in directories:
                model.append([f])

            table = gtk.Table(rows=2, columns=1)
            items = [
                ("Add...", self.__add_directory),
                ("Remove", self.__remove_directory),
                ("Rescan all", self.__rescan_all)
            ]
            for idx, (label, callback) in enumerate(items):
                button = gtk.Button(label)
                button.connect("clicked", callback, treeview)
                table.attach(button, 0, 1, idx, idx+1, yoptions=not gtk.EXPAND)

            hbox.pack_start(sw, expand=True)
            hbox.pack_start(table, expand=False, fill=False)

            # Update library checkbutton
            update_library = gtk.CheckButton("Update library on startup")
            update_library.set_active(
                blacfg.getboolean("library", "update.on.startup"))
            update_library.connect(
                "toggled",
                lambda cb: blacfg.setboolean("library", "update.on.startup",
                                             cb.get_active()))

            # The file types
            restrict_to_entry = gtk.Entry()
            restrict_to_entry.set_tooltip_text(
                "Comma-separated list, works on filenames")
            restrict_to_entry.set_text(
                blacfg.getstring("library", "restrict.to"))
            restrict_to_entry.connect(
                "changed",
                lambda entry: blacfg.set("library", "restrict.to",
                                         entry.get_text()))

            exclude_entry = gtk.Entry()
            exclude_entry.set_tooltip_text(
                "Comma-separated list, works on filenames")
            exclude_entry.set_text(
                blacfg.getstring("library", "exclude"))
            exclude_entry.connect(
                "changed",
                lambda entry: blacfg.set("library", "exclude",
                                         entry.get_text()))

            pairs = [
                (blaconst.ACTION_SEND_TO_CURRENT, "send to current playlist"),
                (blaconst.ACTION_ADD_TO_CURRENT, "add to current playlist"),
                (blaconst.ACTION_SEND_TO_NEW, "send to new playlist"),
                (blaconst.ACTION_EXPAND_COLLAPSE, "expand/collapse")
            ]
            # FIXME: Ugly!!
            actions = [""] * 4
            for idx, label in pairs:
                actions[idx] = label
            comboboxes = []

            def cb_changed(combobox, key):
                blacfg.set("library", "%s.action" % key, combobox.get_active())

            for key in ["doubleclick", "middleclick", "return"]:
                cb = gtk.combo_box_new_text()
                map(cb.append_text, actions)
                if key == "return":
                    cb.remove_text(3)
                cb.set_active(blacfg.getint("library", "%s.action" % key))
                cb.connect("changed", cb_changed, key)
                comboboxes.append(cb)

            widgets = [restrict_to_entry, exclude_entry] + comboboxes
            labels = ["Restrict to", "Exclude", "Double-click", "Middle-click",
                      "Return"]

            action_table = gtk.Table(rows=len(labels), columns=2,
                                     homogeneous=False)

            count = 0
            for label, widget in zip(labels, widgets):
                label = gtk.Label("%s:" % label)
                label.set_alignment(xalign=0.0, yalign=0.5)
                action_table.attach(label, 0, 1, count, count+1,
                                    xoptions=gtk.FILL, xpadding=5)
                action_table.attach(widget, 1, 2, count, count+1)
                count += 1

            hbox2 = gtk.HBox(spacing=10)

            draw_tree_lines = gtk.CheckButton("Draw tree lines in browsers")
            draw_tree_lines.set_active(
                blacfg.getboolean("general", "draw.tree.lines"))
            draw_tree_lines.connect("toggled", self.__tree_lines_changed)

            custom_library_browser = gtk.CheckButton(
                "Use custom treeview as library browser")
            custom_library_browser.set_active(
                blacfg.getboolean("library", "custom.browser"))
            custom_library_browser.connect(
                "toggled", self.__custom_library_browser_changed)

            hbox2.pack_start(draw_tree_lines)
            hbox2.pack_start(custom_library_browser)

            self.pack_start(hbox, expand=False)
            self.pack_start(update_library, expand=False)
            self.pack_start(action_table, expand=False)
            self.pack_start(hbox2, expand=False)

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

        def __tree_lines_changed(self, checkbutton):
            blacfg.setboolean(
                "general", "draw.tree.lines", checkbutton.get_active())
            BlaBrowsers.update_tree_lines()

        def __custom_library_browser_changed(self, checkbutton):
            blacfg.setboolean(
                "library", "custom.browser", checkbutton.get_active())
            blagui.update_colors()

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

            self.__profiles_box = gtk.combo_box_new_text()
            self.__profiles_box.connect("changed", self.__profile_changed)

            old_profile = blacfg.getstring("player", "equalizer.profile")
            profiles = blacfg.get_keys("equalizer.profiles")

            for idx, profile in enumerate(profiles):
                self.__profiles_box.append_text(profile[0])
                if profile[0] == old_profile:
                    self.__profiles_box.set_active(idx)

            button_table = gtk.Table(rows=1, columns=3, homogeneous=True)
            new_profile_button = gtk.Button("New")
            new_profile_button.connect(
                "clicked", self.__new_profile, self.__profiles_box)
            delete_profile_button = gtk.Button("Delete")
            delete_profile_button.connect(
                "clicked", self.__delete_profile, self.__profiles_box)
            reset_profile_button = gtk.Button("Reset")
            reset_profile_button.connect_object(
                "clicked", BlaPreferences.PlayerSettings.__reset_profile, self)
            button_table.attach(new_profile_button, 0, 1, 0, 1, xpadding=2)
            button_table.attach(delete_profile_button, 1, 2, 0, 1, xpadding=2)
            button_table.attach(reset_profile_button, 2, 3, 0, 1, xpadding=2)

            self.__button_box = gtk.HBox()
            self.__button_box.pack_start(
                gtk.Label("Profiles:"), expand=False, padding=10)
            self.__button_box.pack_start(self.__profiles_box, expand=False)
            self.__button_box.pack_start(
                button_table, expand=False, padding=16)

            table = gtk.Table(rows=2, columns=2, homogeneous=False)
            table.set_row_spacings(2)
            table.attach(logarithmic_volume_scale, 0, 2, 0, 1, xpadding=2)
            table.attach(use_equalizer, 0, 1, 1, 2, xpadding=2)
            table.attach(self.__button_box, 1, 2, 1, 2, xpadding=2)

            self.__scale_box = gtk.HBox(homogeneous=True)

            bands = [29, 59, 119, 237, 474, 947, 1889, 3770, 7523, 15011]
            values = blacfg.getlistfloat("equalizer.profiles", old_profile)
            if not values:
                values = [0] * blaconst.EQUALIZER_BANDS
            for idx, val in enumerate(values):
                box = gtk.VBox(spacing=10)
                scale = gtk.VScale(gtk.Adjustment(val, -24., 12., 0.1))
                scale.set_inverted(True)
                scale.set_update_policy(gtk.UPDATE_DISCONTINUOUS)
                scale.set_value(values[idx])
                scale.set_digits(1)
                scale.set_draw_value(True)
                scale.set_value_pos(gtk.POS_BOTTOM)
                scale.connect("value_changed", self.__equalizer_value_changed,
                              idx, self.__profiles_box)
                scale.connect("format_value", lambda *x: "%.1f dB" % x[-1])
                self.__scales.append(scale)

                label = gtk.Label("%d Hz" % bands[idx])
                box.pack_start(label, expand=False)
                box.pack_start(scale, expand=True)
                self.__scale_box.pack_start(box)

            self.pack_start(table, expand=False, padding=10)
            self.pack_start(self.__scale_box, expand=True)

            self.__use_equalizer_changed(use_equalizer)

        def __volume_scale_changed(self, checkbutton):
            blacfg.setboolean("player", "logarithmic.volume.scale",
                              checkbutton.get_active())
            player.set_volume(blacfg.getfloat("player", "volume") * 100)

        def __use_equalizer_changed(self, checkbutton):
            state = checkbutton.get_active()
            blacfg.setboolean("player", "use.equalizer", state)
            player.enable_equalizer(state)
            self.__button_box.set_sensitive(state)

            if state and not self.__profiles_box.get_model().get_iter_first():
                self.__scale_box.set_sensitive(False)
            else:
                self.__scale_box.set_sensitive(state)

        def __reset_profile(self):
            for s in self.__scales:
                s.set_value(0)

        def __equalizer_value_changed(self, scale, band, combobox):
            profile_name = combobox.get_active_text()
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
                self.__scale_box.set_sensitive(False)

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

                self.__scale_box.set_sensitive(True)

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

            sw = BlaScrolledWindow()
            sw.set_shadow_type(gtk.SHADOW_IN)
            sw.add(treeview)

            self.pack_start(sw, expand=True)
            if not blakeys.can_bind():
                label = gtk.Label()
                label.set_markup(
                    "<b>Note</b>: The <i>keybinder</i> module is not "
                    "available on the system.\nAs a result, the settings on "
                    "this page will have no effect.")
                self.pack_start(label, expand=False, padding=20)

    class LastfmSettings(Page):
        def __init__(self):
            super(BlaPreferences.LastfmSettings, self).__init__("last.fm")

            self.connect("destroy", self.__save)

            scrobble = gtk.CheckButton("Enable scrobbling")
            scrobble.set_active(blacfg.getboolean("lastfm", "scrobble"))
            scrobble.connect("toggled", self.__scrobble_changed)

            self.__user_entry = gtk.Entry()
            self.__user_entry.set_text(blacfg.getstring("lastfm", "user"))

            self.__ignore_entry = gtk.Entry()
            self.__ignore_entry.set_text(
                    blacfg.getstring("lastfm", "ignore.pattern"))
            self.__ignore_entry.set_tooltip_text("Comma-separated list")

            nowplaying = gtk.CheckButton("Submit \"Listening now\" messages")
            nowplaying.set_active(blacfg.getboolean("lastfm", "now.playing"))
            nowplaying.connect("toggled", self.__nowplaying_changed)

            count = 0
            pairs = [
                ("Username", self.__user_entry),
                ("Ignore pattern", self.__ignore_entry)
            ]

            table = gtk.Table(rows=len(pairs), columns=2, homogeneous=False)
            count = 0
            for label, widget in pairs:
                label = gtk.Label("%s:" % label)
                label.set_alignment(xalign=0.0, yalign=0.5)
                table.attach(label, 0, 1, count, count+1, xoptions=gtk.FILL,
                             xpadding=5)
                table.attach(widget, 1, 2, count, count+1)
                count += 1

            self.pack_start(scrobble, expand=False)
            self.pack_start(table, expand=False)
            self.pack_start(nowplaying, expand=False)

        def __save(self, *args):
            blacfg.set("lastfm", "user", self.__user_entry.get_text())
            blacfg.set("lastfm", "ignore.pattern",
                       self.__ignore_entry.get_text())

        def __scrobble_changed(self, checkbutton):
            blacfg.setboolean("lastfm", "scrobble", checkbutton.get_active())

        def __nowplaying_changed(self, checkbutton):
            blacfg.setboolean("lastfm", "now.playing",
                              checkbutton.get_active())

    def __init__(self, *args):
        super(BlaPreferences, self).__init__()

        self.set_resizable(False)
        self.set_title("%s Preferences" % blaconst.APPNAME)

        notebook = gtk.Notebook()
        for page in [self.GeneralSettings, self.LibraryBrowsersSettings,
                     self.PlayerSettings, self.Keybindings,
                     self.LastfmSettings]:
            try:
                page = page()
            except Exception as exc:
                print_d(exc)
                continue
            notebook.append_page(page, gtk.Label(page.name))
        self.vbox.pack_start(notebook)
        self.show_all()

