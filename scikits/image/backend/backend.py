import os, sys
import scikits.image.backends
import ast


class ModuleParser(ast.NodeVisitor):
    """
    Parser that extracts all defined methods from source without importing.
    """
    def parse(self, code):
        """
        Parses source code and visit definitions.
        """
        tree = ast.parse(code)
        self.functions = []
        self.visit(tree)
        return self.functions
    
    def visit_FunctionDef(self, statement):
        """
        Function visitation of parser.
        """
        self.functions.append(statement.name)


def import_backend(backend, module_name):
    """
    Imports the backend counterpart of a module.
    """
    mods = module_name.split(".")
    module_name = ".".join(mods[:-1] + ["backend"] + [mods[-1]])
    name = module_name + "_%s" % backend
    try:
        return __import__(name, fromlist=[name])
    except ImportError:
        return None


class BackendManager(object):
    """
    Backend manager handles backend registry and switching.
    """
    def __init__(self):
        # add default numpy to backends namespace
        mod = sys.modules["scikits.image.backends"]
        setattr(mod, "numpy", "numpy")        
        self.current_backend = "numpy"
        self.current_backends = {}
        self.backend_listing = {}
        self.backend_imported = {}
        self.scan_backends()
        self.parser = ModuleParser()
    
    def scan_backends(self):
        """
        Scans through the source tree to extract all available backends.
        """        
        root = "scikits.image"
        location = os.path.split(sys.modules[root].__file__)[0]
        backends = []
        # visit each backend directory in every scikits.image submodule
        for f in os.listdir(location):
            submodule = os.path.join(location, f)
            if os.path.isdir(submodule):
                submodule_dir = submodule
                module_name = root + "." + f
                backend_dir = os.path.join(location, f, "backend")
                if os.path.exists(backend_dir):
                    submodule_files = [f for f in os.listdir(submodule_dir) \
                        if os.path.isfile(os.path.join(submodule_dir, f)) and f.endswith(".py")]
                    backend_files = [f for f in os.listdir(backend_dir) \
                        if os.path.isfile(os.path.join(backend_dir, f)) and f.endswith(".py")]
                    # math file in backend directory with file in parent directory
                    for f in backend_files:
                        split = f.split("_")
                        backend = split[-1][:-3]
                        target = "_".join(split[:-1])
                        if target + ".py" in submodule_files:
                            if backend not in backends:
                                backends.append(backend)
                            mod_name = module_name + "." + target
                            if mod_name not in self.backend_listing:
                                # initialize default numpy backend
                                self.backend_listing[mod_name] = {}
                                self.backend_listing[mod_name]["numpy"] = {}
                                self.backend_imported[mod_name] = {}
                                self.backend_imported[mod_name]["numpy"] = True
                            self.backend_listing[mod_name][backend] = {}
                            self.backend_imported[mod_name][backend] = False
        # create references for each backend in backends namespace
        backends_mod = sys.modules["scikits.image.backends"]
        for backend_name in backends:
            setattr(backends_mod, backend_name, backend_name)

    def use_backend(self, backend):
        """
        Selects a new backend and update modules as needed.
        """
        self.current_backend = backend
        for module_name in self.backend_imported.keys():
            # check if backend has been imported and if not do so
            print module_name, backend
            if backend in self.backend_imported[module_name] \
            and not self.backend_imported[module_name][backend]:
                backend_module = import_backend(backend, module_name)
                self.backend_imported[module_name][backend] = True
                for function_name in self.backend_listing[module_name][backend].keys():
                    self.backend_listing[module_name][backend][function_name] = \
                        getattr(backend_module, function_name)

    def scan_backend_functions(self, module_name):
        """
        Scans through the registered backends of a module and extract the defined functions
        """
        module_path = os.path.split(sys.modules[module_name].__file__)[0]
        main_name = module_name.split('.')[-1]
        functions = {}
        print self.backend_listing[module_name].keys(), module_name, module_path, main_name
        for backend in self.backend_listing[module_name].keys():
            if backend != "numpy":
                backend_path = os.path.join(module_path, "backend", main_name + "_" + backend + ".py")
                functions[backend] = self.parser.parse(open(backend_path).read())
        return functions

    def backend_function_name(self, function, backend):
        module_elements = function.__module__.split(".")
        return ".".join(module_elements[:-1] + ["backend"] + [module_elements[-1] + "_" + backend] + [function.__name__])
    
    def register_function(self, module_name, function):
        """
        Register functions for a specific module
        """
        backend = self.current_backend
        function_name = function.__name__
        if module_name not in self.backend_listing:
            self.backend_listing[module_name] = {}
            self.backend_listing[module_name]["numpy"] = {}
        # parse backend files and initialize implemented functions
        if len(self.backend_listing[module_name]["numpy"]) == 0:
            functions = self.scan_backend_functions(module_name)
            for backend, backend_functions in functions.items():
                for backend_function in backend_functions:
                    self.backend_listing[module_name][backend][backend_function] = None
        # register numpy implementation
        self.backend_listing[module_name]["numpy"][function_name] = function
        # if current backend is other than default, do the required backend imports
        if not self.backend_imported[module_name][backend]:
            # register backend function
            backend_module = import_backend(backend, module_name)
            self.backend_imported[module_name][backend] = True
            self.backend_listing[module_name][backend][function_name] = \
                    getattr(backend_module, function_name)
        

manager = BackendManager()
use_backend = manager.use_backend        


class add_backends(object):
    """
    Decorator that adds backend support to a function.
    """
    def __init__(self, *backends):
        pass
                
    def __call__(self, function):
        self.function = function
        self.function_name = function.__name__
        self.module_name = function.__module__
        # iterate through backend directory and find backends that match
        manager.register_function(self.module_name, function)
        # add documentation to function doc strings
        if len(manager.backend_listing[self.module_name]) > 1:
            if not function.__doc__:
                function.__doc__ = ""
            else:
                function.__doc__ += "\n"
            function.__doc__ += "    Backends supported:\n"
            function.__doc__ += "    -------------------\n"
            for backend in manager.backend_listing[self.module_name].keys():
                function.__doc__ += "    %s\n" % backend
                function.__doc__ += "       See also: %s\n" % manager.backend_function_name(function, backend)
        
        def wrapped_f(*args, **kwargs):
            if "backend" in kwargs:
                backend = kwargs.get("backend")
                del kwargs["backend"]
            else:
                backend = manager.current_backend
            # fall back to numpy if function not provided
            if backend not in manager.backend_listing[self.module_name] or \
            self.function_name not in manager.backend_listing[self.module_name][backend]:
                backend = "numpy"
#                if manager.required:
#                    raise RuntimeError("No backend support for function call")
            return manager.backend_listing[self.module_name][backend][self.function_name](*args, **kwargs)
        
        wrapped_f.__doc__ = function.__doc__
        wrapped_f.__module__ = function.__module__
        return wrapped_f