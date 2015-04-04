import sublime_plugin, sublime, os, sys, re, urllib, urllib.parse, threading, socket, json

from time import time

from .lib.urllib3 import PoolManager

IS_EXTERNAL_SERVER_ENABLE = False
AC_OPTS = sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS

launcher_procs = {
}

server_ports = {
}

if sys.version_info < (3, 3):
    raise RuntimeError('OmniSharpSublime works with Sublime Text 3 only')

pool = PoolManager(headers={'Content-Type': 'application/json; charset=UTF-8'})
    
def plugin_loaded():
    print('omnisharp plugin_loaded')
    settings = sublime.load_settings('OmniSharpSublime.sublime-settings')
    configpath = settings.get("omnisharp_server_config_location")
    if not configpath:
        settings.set("omnisharp_server_config_location", sublime.packages_path() + os.path.sep + "OmniSharp" + os.path.sep + "PrebuiltOmniSharpServer" + os.path.sep + "config.json")
        sublime.save_settings('OmniSharpSublime.sublime-settings')

def plugin_unloaded():
    print('omnisharp plugin_unloaded')
    
class OmniSharpServerRunnerEventListener(sublime_plugin.EventListener):
    def on_activated(self, view):
        if not is_csharp(view):
            return
            
        create_omnisharp_server_subprocess(view)
    
class OmniSharpAddFileToProjectEventListener(sublime_plugin.EventListener):
    def on_post_save(self, view):
        if not is_csharp(view):
            return

        get_response(view, '/addtoproject', self.add_to_project)

    def add_to_project(self, data):
        print('file added to project')
        print(data)

class OmniSharpOverrideListener(sublime_plugin.EventListener):
    view = None

    def on_modified(self, view):
        if not is_csharp(view):
            return

        pos = view.sel()[0].begin()
        if pos > 9: #override 
            reg = sublime.Region(pos-9, pos)
            keyword = view.substr(reg).strip();
            if keyword == 'override':
                override_targets(view)

    def override_targets(view):
        view.run_command('omni_sharp_override_targets')
        
class OmniSharpTooltipListener(sublime_plugin.EventListener):

    def on_activated_async(self, view):
        self._check_tooltip(view)

    def on_modified_async(self, view):
        self._check_tooltip(view)

    def on_selection_modified_async(self, view):
        self._check_tooltip(view)

    def _check_tooltip(self, view):

        view_settings = view.settings()
        if view_settings.get('is_widget'):
            return

        oops_map = view.settings().get("oops")
        if None == oops_map:
            return

        for region in view.sel():

            row_col = view.rowcol(region.begin())
            word_region = view.word(region.begin())
            word = view.substr(word_region)

            key = "%s,%s" % (word_region.a, word_region.b)
            if key not in oops_map:
                continue
            issue = oops_map[key]

            css = "html {background-color: #232628; color: #CCCCCC; } body {font-size: 12px; } a {color: #6699cc; } b {color: #cc99cc; } h1 {color: #99cc99; font-size: 14px; }"
            html = ['<style>%s</style>' % css]
            html.append(issue)

            view.show_popup(''.join(html), location=-1, max_width=600, on_navigate=self.on_navigate)

            return

        view.hide_popup()

    def on_navigate(self, link):
        return

        
class OmniSharpSyntaxEventListener(sublime_plugin.EventListener):
    data = None
    view = None
    outputpanel = None
    next_run_time = 0

    def on_post_save(self, view):
        self._run_codecheck(view)

    def on_modified(self, view):
        timeout_ms = 500
        self.next_run_time = time() + 0.0009 * timeout_ms
        sublime.set_timeout(lambda:self._run_codecheck_after_delay(view), timeout_ms)

    def _run_codecheck_after_delay(self, view):
        if self.next_run_time <= time():
            self._run_codecheck(view)

    def _run_codecheck(self, view):
        if not is_csharp(view):
            return
        
        self.view = view

        sublime.active_window().run_command("hide_panel",{"panel": "output.variable_get"})
        self.outputpanel = self.view.window().create_output_panel("variable_get")
        self.outputpanel.run_command('erase_view')

        self.view.erase_regions("oops")
        if bool(get_settings(view, 'omnisharp_onsave_codecheck')):
            get_response(view, '/codecheck', self._handle_codeerrors)

        print('file changed')

    def _handle_codeerrors(self, data):
        print('handling Errors')
        if data is None:
            print('no data')
            return
        
        self.data = data
        self.underlines = []
        oops_map = {}

        if "QuickFixes" in self.data and self.data["QuickFixes"] != None and len(self.data["QuickFixes"]) > 0:
            for i in self.data["QuickFixes"]:
                point = self.view.text_point(i["Line"]-1, i["Column"])
                reg = self.view.word(point)
                self.underlines.append(reg)
                key = "%s,%s" % (reg.a, reg.b)
                oops_map[key] = i["Text"].strip()
                self.outputpanel.run_command('append', {'characters': i["LogLevel"] + " : " + i["Text"].strip() + " - (" + str(i["Line"]) + ", " + str(i["Column"]) + ")\n"})
            if len(self.underlines) > 0:
                print('underlines')
                self.view.settings().set("oops", oops_map)
                self.view.add_regions("oops", self.underlines, "illegal", "", sublime.DRAW_NO_FILL + sublime.DRAW_NO_OUTLINE + sublime.DRAW_SQUIGGLY_UNDERLINE)
                if bool(get_settings(self.view,'omnisharp_onsave_showerrorwindows')):
                    self.view.window().run_command("show_panel", {"panel": "output.variable_get"})

        self.data = None


class OmniSharpCompletionEventListener(sublime_plugin.EventListener):

    completions = []
    ready_form_defer = False

    def on_query_completions(self, view, prefix, locations):

        if not is_csharp(view):
            return

        if self.ready_form_defer is True:
            cpl = self.completions
            self.completions = []
            self.ready_form_defer = False
            return cpl

        if re.match("^\W*$", prefix):
            word_to_complete = ''
        else:
            word_to_complete = prefix

        params = {}
        params['wordToComplete'] = word_to_complete
        params['WantSnippet'] = True
        params['WantMethodHeader'] = True
        params['WantReturnType'] = True 
        get_response(view, '/autocomplete', self._complete, params)
        return ([], AC_OPTS)

    def _complete(self, data):
        if data is None:
            return
        
        completions = []
        for item in data:
            completions.append(self.to_completion(item))

        hide_auto_complete(active_view())
        self.completions = completions 
        self.ready_form_defer = True

        self._run_auto_complete()

    def _run_auto_complete(self):
        active_view().run_command("auto_complete", {
            'disable_auto_insert': True,
            'api_completions_only': True,
            'next_completion_if_showing': False,
            'auto_complete_commit_on_tab': True,
        })

    def to_completion(self, json):
        display = json['MethodHeader'] if json['MethodHeader'] is not None and len(json['MethodHeader']) > 0 else json['CompletionText']
        display += '\t'
        display += json['ReturnType'] if json['ReturnType'] is not None and len(json['ReturnType']) > 0 else json['DisplayText']

        completionText = json['Snippet'] if json['Snippet'] is not None and len(json['Snippet']) > 0 else json['DisplayText']

        return (display, completionText)

        
def hide_auto_complete(view):
    view.run_command('hide_auto_complete')

def is_csharp(view):
    try:
        location = view.sel()[0].begin()
    except:
        return False

    return view.match_selector(location, 'source.cs')


def get_settings(view, name, default=None):
    settings = sublime.load_settings('OmniSharpSublime.sublime-settings')
    from_plugin = settings.get(name, default)
    return view.settings().get(name, from_plugin)

def active_view():
    return sublime.active_window().active_view()


def project_file_name(view):
    return view.window().project_file_name()

def project_data(view):
    return view.window().project_data()

def current_solution_filepath_or_project_rootpath(view):
    project_file = project_file_name(view)
    if project_file is not None:
        print('project file found')
        project_dir = os.path.dirname(project_file)

        data = project_data(view)
        if 'solution_file' not in data:
            raise ValueError('Please specify a path to the solution file in your sublime-project file or delete it')
        else:
            solution_file_name = data['solution_file']
            solution_file_path = os.path.join(project_dir, solution_file_name)
            solution_file_path = os.path.abspath(solution_file_path)
            return solution_file_path
    else:
        parentpath = sublime.active_window().folders()[0] #assume parent folder is opened that contains all project folders eg/Web,ClassLib,Tests
        return parentpath


class WorkerThread(threading.Thread):
    def __init__(self, url, data, callback, timeout):
        threading.Thread.__init__(self)
        self.url = url
        self.data = data
        self.callback = callback
        self.timeout = timeout

    def run(self):
        print('======== request ======== \n Url: %s \n Data: %s' % (self.url, self.data))
        
        response = pool.urlopen('POST', self.url, body=self.data, timeout=self.timeout).data
        
        if not response:
            print('======== response ======== \n response is empty')
            self.callback(None)
        else:
            decodeddata = response.decode('utf-8')
            print('======== response ======== \n %s' % decodeddata)
            self.callback(json.loads(decodeddata))
            
        print('======== end ========')

def get_response(view, endpoint, callback, params=None, timeout=None):
    solution_path =  current_solution_filepath_or_project_rootpath(view)

    print('solution path: %s' % solution_path)
    if solution_path is None or solution_path not in server_ports:
        callback(None)
        return
        
    location = view.sel()[0]
    cursor = view.rowcol(location.begin())

    parameters = {}
    parameters['line'] = str(cursor[0] + 1)
    parameters['column'] = str(cursor[1] + 1)
    parameters['buffer'] = view.substr(sublime.Region(0, view.size()))
    parameters['filename'] = view.file_name()

    if params is not None:
        parameters.update(params)

    if timeout is None:
        timeout = int(get_settings(view, 'omnisharp_response_timeout'))
        
    host = 'localhost'
    port = server_ports[solution_path]

    url = "http://%s:%s%s" % (host, port, endpoint)
    data = json.dumps(parameters)

    thread = WorkerThread(url, data, callback, timeout)  
    thread.start()

def _available_port():
    if IS_EXTERNAL_SERVER_ENABLE:
        return 2000

    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()

    return port

def create_omnisharp_server_subprocess(view):
    solution_path = current_solution_filepath_or_project_rootpath(view) 
    if solution_path in launcher_procs:
        print("already_bound_solution:%s" % solution_path)
        return

    print("solution_path:%s" % solution_path)

    omni_port = _available_port()
    print('omni_port:%s' % omni_port)
    
    
    config_file = get_settings(view, "omnisharp_server_config_location")

    if IS_EXTERNAL_SERVER_ENABLE:
        launcher_proc = None
        omni_port = 2000
    else:
        try:
            omni_exe_paths = find_omni_exe_paths()
            omni_exe_path = "\"" + omni_exe_paths[0] + "\""
            
            args = [
                omni_exe_path, 
                '-s', '"' + solution_path + '"',
                '-p', str(omni_port),
                '-config', '"' + config_file + '"',
                '--hostPID', str(os.getpid())
            ]

            cmd = ' '.join(args)
            print(cmd)
            
            view.window().run_command("exec",{"cmd":cmd,"shell":"true","quiet":"true"})
            view.window().run_command("hide_panel", {"panel": "output.exec"})

        except Exception as e:
            print('RAISE_OMNI_SHARP_LAUNCHER_EXCEPTION:%s' % repr(e))
            return

    launcher_procs[solution_path] = True
    server_ports[solution_path] = omni_port

def find_omni_exe_paths():
    source_file_path = os.path.realpath(__file__)
        
    if os.name == 'posix':
        script_name = 'omnisharp'
    else:
        source_file_path = source_file_path.replace('\\', '/')
        script_name = 'omnisharp.cmd'

    source_dir_path = os.path.dirname(source_file_path)
    plugin_dir_path = os.path.dirname(source_dir_path)

    omni_exe_candidate_rel_paths = [
        'Omnisharp/omnisharp-roslyn/artifacts/build/omnisharp/' + script_name,
        'Omnisharp/PrebuiltOmniSharpServer/' + script_name,
    ]

    omni_exe_candidate_abs_paths = [
        '/'.join((plugin_dir_path, rel_path))
        for rel_path in omni_exe_candidate_rel_paths
    ]
    
    return [omni_exe_path 
        for omni_exe_path in omni_exe_candidate_abs_paths
        if os.access(omni_exe_path, os.R_OK)]


