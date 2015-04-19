import os
import sublime
import sublime_plugin
from time import time

from ..lib import helpers
from ..lib import omnisharp


class OmniSharpSyntaxEventListener(sublime_plugin.EventListener):
    view = None
    outputpanel = None
    next_run_time = 0
    is_save = False
    is_modify = False

    def on_activated(self, view):
        self._run_codecheck_after_delay(view)

    def on_modified(self, view):
        self.is_modify = True
        self._run_codecheck_after_delay(view)

    def on_post_save(self, view):
        self.is_save = True
        self._run_codecheck_after_delay(view)

    def _run_codecheck_after_delay(self, view):
        timeout_ms = 500
        self.next_run_time = time() + 0.0009 * timeout_ms
        sublime.set_timeout(lambda:self._run_codecheck_after_delay_callback(view), timeout_ms)

    def _run_codecheck_after_delay_callback(self, view):
        if self.next_run_time <= time():
            self._run_codecheck(view)

    def _run_codecheck(self, view):
        if not helpers.is_csharp(view):
            return
        
        self.view = view

        sublime.active_window().run_command("hide_panel",{"panel": "output.variable_get"})
        self.outputpanel = self.view.window().create_output_panel("variable_get")
        self.outputpanel.run_command('erase_view')

        self.view.erase_regions("oops")
        if bool(helpers.get_settings(view, 'omnisharp_onsave_codecheck')) and self.is_save:
            omnisharp.get_response(view, '/codecheck', self._handle_codeerrors)

        print('file changed')

    def _handle_codeerrors(self, data):
        print('handling errors')
        if data is None:
            print('no data')
            return
        
        self.underlines = []
        oops_map = {}

        if "QuickFixes" in data and data["QuickFixes"] != None and len(data["QuickFixes"]) > 0:
            for i in data["QuickFixes"]:
                point = self.view.text_point(i["Line"]-1, i["Column"]-1)
                reg = self.view.word(point)
                region_that_would_be_looked_up = self.view.word(reg.begin())
                if region_that_would_be_looked_up.begin() != reg.begin() or region_that_would_be_looked_up.end() != reg.end():
                    reg = sublime.Region(point, point+1)
                self.underlines.append(reg)
                key = "%s,%s" % (reg.a, reg.b)
                oops_map[key] = i["Text"].strip()
                self.outputpanel.run_command('append', {'characters': i["LogLevel"] + " : " + i["Text"].strip() + " - (" + str(i["Line"]) + ", " + str(i["Column"]) + ")\n"})
            if len(self.underlines) > 0:
                print('underlines')
                self.view.settings().set("oops", oops_map)
                self.view.add_regions("oops", self.underlines, "illegal", "", sublime.DRAW_NO_FILL + sublime.DRAW_NO_OUTLINE + sublime.DRAW_SQUIGGLY_UNDERLINE)
                if bool(helpers.get_settings(self.view,'omnisharp_onsave_showerrorwindows')) and self.is_save:
                    self.view.window().run_command("show_panel", {"panel": "output.variable_get"})