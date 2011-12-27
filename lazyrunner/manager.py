"""
A class that manages a batch of sessions.  
"""

import time, logging, sys
from diskio import *
import os, os.path as osp
from pmodulelookup import *
from treedict import TreeDict

        
class Manager(object):
    """
    The command and control center for coordinating the sessions.
    
    The main aspect of this is caching, which is implemented by
    storing the elements of the cache in files named the hash of their
    parameters.
    """

    def __init__(self, manager_params):

        self.manager_params = mp = manager_params

        self.log = logging.getLogger("Manager")

        # set up the result cache
        if "cache_directory" in mp and mp.cache_directory is not None:
            
            self.log.info("Using cache directory '%s'" % mp.cache_directory)

            self.cache_directory = osp.expanduser(mp.cache_directory)
            self.use_disk_cache = True
            self.disk_cache_read_only = mp.cache_read_only
        else:
            self.use_disk_cache = False
            self.log.info("Not using disk cache.")

        # Set up the lookups 
        self.local_cache = {}
	self.debug_logged_dependencies = set()



    def run(self, parameters, final_modules = None):

        # Init all the common pools

        



    





    ##################################################
    # Interactions with the PNode structures

    def _buildPNodeTree(self):

        pass

    def _loadFromCache(self, container):

        if self.disk_read_enabled:
            filename = join(self.cache_directory, container.getFilename())
         
            if exists(filename):
                try:
                    pt = loadResults(filename)
                except Exception, e:
                    self.log.error("Exception Raised while loading %s: \n%s"
                                   % (filename, str(e)))
                    pt = None
                    
                if pt is not None:

                    if (pt.treeName() == "__ValueWrapper__"
                        and pt.size() == 1
                        and "value" in pt):
                    
                        container.setObject(pt.value)
                    else:
                        container.setObject(pt)
                        
                    return

        if self.disk_write_enabled:
            container.setObjectSaveHook(self._saveToCache)


    def _saveToCache(self, container):
            
        if self.disk_write_enabled:

            filename = join(self.cache_directory, container.getFilename())
            directory = split(filename)[0]

                # Make sure it exists
            if not osp.exists(directory):
                os.makedirs(directory)

            if type(obj) is not TreeDict:
                pt = TreeDict("__ValueWrapper__")
                pt.value = obj
            else:
                pt = obj

            try:
                saveResults(filename, pt)
            except Exception, e:
                self.log.error("Exception raised attempting to save object to cache: \n%s" % str(e))

                try:
                    os.remove(filename)
                except Exception:
                    pass


    ##################################################
    # Interface functions to the outside

    def getResults(self, parameters, name = None):
        """
        The main method for getting results from the outside.  If
        these results are already present, then they are returned as is.
        """

        # make sure that all the flags are removed from the parameter
        # tree; things should be reprocessed here.
        parameters.attach(recursive = True)
        parameters = parameters.copy()


        if name is None or type(name) in [list, tuple, set]:
            if name is None:

                name = parameters.get("run_queue", [])

                if type(name) is str:
                    name = [name]

                self.log.debug("Results requested for modules %s, from run_queue." % (", ".join(name)))
            else:
                self.log.debug("Results requested for modules %s." % (", ".join(name)))

            r = TreeDict("results")

            # important to have copy of run_queue here!
            for n in [nn.lower() for nn in name]:
                if n not in r:
                    r[n] = self._getResults(parameters, n)

            r.freeze()

            return r

        elif type(name) is str:
            self.log.debug("Results requested for module '%s'" % name)
            return self._getResults(parameters, name.lower())

        else:
            raise TypeError("'%s' not a valid type for name parameter." % str(type(name)))

    def _getResults(self, parameters, name, key = None, module_instance = None):

        assert type(name) is str
        name = name.lower()

        self.log.debug("Retriveing results for module '%s'" % name)

        # Get the hash of this module
        if key is None:
            key = self._getModuleKey(parameters, name)

        if self.inCache(key, "results"):
            r = self.loadFromCache(key, "results")
            self.__reportResults(parameters, name, key, r)

        else:
            self.log.debug("Getting results for %s" % name)

            if module_instance is None:
                module_instance, r = self._getModule(parameters, name, key=key, calling_from_getresults = True)
            else:
                self.log.info("Running %s" % name)
                r = module_instance.run()

            if r is None:
                r = TreeDict()
                r.freeze()
            else:
                r.freeze()

            self.saveToCache(key, "results", r)
            self.__reportResults(parameters, name, key, r)

        return r

    def getModule(self, parameters, name):
        """
        Returns a given module of that type.  
        """

        return self._getModule(parameters.copy(), name.lower())

    def _getModule(self, parameters, name, key = None, calling_from_getresults = False):

        # Only save one module of each to keep the memory use down

        self.log.debug("Retrieving module %s" % name)

        if key is None:
            key = self._getModuleKey(parameters, name)

        m = None

        if name in self.current_modules:
            cur_key, cur_m = self.current_modules[name]

            if cur_key == key:
                m = cur_m

        if m is None:
            self.log.debug("Instantiating module %s" % name)
            m = getPModuleClass(name)(self, key, parameters, True)

        assert m._name == name, "m._name <- %s != %s -> name" % (m._name, name)

        self.current_modules[name] = (key, m)

        r = self._getResults(parameters, name, key, module_instance = m)

        # Give it the local results
        m.local_results = r

        # If we're calling from getResults, return r along with m
        if calling_from_getresults:
            return m, r
        else:
            return m

    def _getModuleKey(self, parameters, name):

        def getHashDependencySet(n):

            pmc = getPModuleClass(n)
            pdep_set = pmc._getDependencySet(self, parameters, "parameter")

            for d in (pmc._getDependencySet(self, parameters, "result")
                      | pmc._getDependencySet(self, parameters, "module") ):

                if d != n:
                    pdep_set |= getHashDependencySet(d)

            pdep_set_string = ', '.join(sorted(pdep_set))

            if ("parameter", n, pdep_set_string) not in self.debug_logged_dependencies:
                self.log.debug("Parameter dependencies for %s are %s" % (n, pdep_set_string))
                self.debug_logged_dependencies.add( ("parameter", n, pdep_set_string) )

            return pdep_set

        d_set = sorted(getHashDependencySet(name))

        dep_td = TreeDict()

        d_set_str = ', '.join(d_set)

        if ("hash", name, d_set_str) not in self.debug_logged_dependencies:
            self.log.debug("Hash Dependency set for %s is %s" % (name, d_set_str))
            self.debug_logged_dependencies.add( ("hash", name, d_set_str) )

        # Set the dependency hash
        for d in d_set:
            if d != name:
                dep_td[d] = self.getPreprocessedBranch(parameters, d, return_hash = True)[1]

        dep_hash = dep_td.hash()

        # Now set the local hash
        local_branch, local_hash = self.getPreprocessedBranch(parameters, name, return_hash = True)

        # if type(local_branch) is TreeDict:
        #     print "\n+++++++++++++ %s ++++++++++++++++" % name
        #     print local_branch.makeReport()
        #     print "+++++++++++++++++++++++++++++"

        return (name, local_hash, dep_hash)

    def __reportResults(self, parameters, name, key, r):

        if (name, key) in self.reported_results:
            return

        self.log.debug("Reporting results for module %s, key = %s" % (name, key))

        p = self.getPreprocessedBranch(parameters, name)

        try:
            getPModuleClass(name).reportResults(parameters, p, r)
        except TypeError, te:

            rrf = getPModuleClass(name).reportResults

            def raiseTypeError():
                raise TypeError(("reportResults method in '%s' must be @classmethod "
                                "and take global parameter tree, local parameter tree, "
                                "and result tree as arguments.") % name)

            # See if it was due to incompatable signature
            try:
                from inspect import getcallargs
            except ImportError:
                if "reportResults" in str(te):
                    raiseTypeError()
                else:
                    raise te

            try:
                getcallargs(rrf, parameters, p, r)
            except TypeError:
                raiseTypeError()

            # Well, that wasn't the issue, so it's something internal; re-raise
            raise

        self.reported_results.add( (name, key) )

    ##################################################
    # Cache file stuff

    def __resultCachingEnabled(self, name):

        cls = getPModuleClass(name)

        if hasattr(cls, 'disable_result_caching') and getattr(cls, 'disable_result_caching'):
            return False
        else:
            return True

    def inCache(self, key, obj_name, local_key_override=None, dependency_key_override=None):
        """
        Returns true if the given object is present in the cache and
        False otherwise.  
        """

    key = self.__processKey(key, local_key_override, dependency_key_override)

    in_cache = False

    if (key, obj_name) in self.local_cache:
        in_cache = True
    else:
        if self.use_disk_cache:
            if (obj_name == "results" and not self.__resultCachingEnabled(key[0])):
                in_cache = False
            else:
                in_cache = osp.exists(self.cacheFile(key, obj_name))
        else:
            in_cache = False

    if in_cache:
        self.log.debug("'%s' with key '%s' in cache." % (obj_name, str(key)))
    else:
        self.log.debug("'%s' with key '%s' NOT in cache." % (obj_name, str(key)))

    return in_cache

    def loadFromCache(self, key, obj_name, local_key_override=None, dependency_key_override=None):
        """
        Loads the results from local cache; returns None if they are
        not present.
        """

        key = self.__processKey(key, local_key_override, dependency_key_override)

        self.log.debug("Loading '%s' from cache with key '%s'" % (obj_name, str(key)))

        try:
            return self.local_cache[(key, obj_name)]
        except KeyError:
            assert self.use_disk_cache

        pt = loadResults(self.cacheFile(key, obj_name))

        assert type(pt) is TreeDict

        if pt.treeName() == "ValueWrapper" and pt.size() == 1 and "value" in pt:
            return pt.value
        else:
            return pt
            
    def saveToCache(self, key, obj_name, obj, local_key_override=None, dependency_key_override=None):
        """
        Saves a given object to cache.
        """

        key = self.__processKey(key, local_key_override, dependency_key_override)

        if obj_name == "results" and not self.__resultCachingEnabled(key[0]):
            return

        self.log.debug("Saving '%s' to cache with key '%s'" % (obj_name, str(key)))

        self.local_cache[(key, obj_name)] = obj

        #if we don't do this, we can run out of memory on a lot of things
        if obj_name == "results":
            if obj_name in self.current_result_keys: 
                try:
                    del self.local_cache[self.current_result_keys[obj_name]]
                except KeyError:
                    pass
            
            self.current_result_keys[obj_name] = (key, obj_name)
        

        if (not self.use_disk_cache or self.disk_cache_read_only):
            return

        filename = self.cacheFile(key, obj_name)

        if type(obj) is not TreeDict:
            pt = TreeDict("__ValueWrapper__")
            pt.value = obj
        else:
            pt = obj

        try:
            saveResults(filename, pt)
        except Exception, e:
            self.log.error("Exception raised attempting to save object to cache: \n%s" % str(e))

            try:
                os.remove(filename)
            except Exception:
                pass

    ##################################################
    # Cache database stuff

    def dbTable(self, key, table_name, *params):
        """
        Returns an sqlalchemy table that the object can 
        """

        # Load the metadata
        
        try:
            metadata = self.local_cache[(key, "db", "metadata")]
        except KeyError:
            
            # See if the engine is already present
            
            try:
                engine = self.local_cache[(key, "db", "engine")]
            except KeyError:
                dbfile = self.cacheFile(key, "database")
                self.local_cache[(key, "db", "engine")] = engine
                                       
            # Open the database
            metadata = MetaData()
            metadata.bind = engine

        return Table(table_name, metadata, *params)

    def dbSession(self, key):
        """
        Returns an active session object for the database
        """
        
        assert False
        
    ##################################################
    # Cache control stuff

    def __processKey(self, key, local_key_override, dependency_key_override):

        assert type(key) is tuple
        assert len(key) == 3
        assert type(key[0]) is str
        assert type(key[1]) is str
        assert type(key[2]) is str
        
        if local_key_override is None and dependency_key_override is None:
            return key

        return (key[0],
                key[1] if local_key_override is None else local_key_override,
                key[2] if dependency_key_override is None else dependency_key_override)

    def _getKeyAsString(self, key, local_key_override, dependency_key_override):

        assert type(key) is tuple
        assert len(key) == 3
        assert type(key[0]) is str
        assert type(key[1]) is str
        assert type(key[2]) is str
        
        return "%s-%s-%s" % (key[0],
                             key[1] if local_key_override is None else local_key_override,
                             key[2] if dependency_key_override is None else dependency_key_override)
        
            
    def cacheFile(self, key, obj_name, suffix=".cache"):
        assert self.cache_directory is not None

        directory = osp.join(self.cache_directory, key[0], obj_name)
        
        # Make sure it exists
        if not osp.exists(directory):
            os.makedirs(directory)

        return osp.join(directory, "-".join(key[1:]) + suffix)

    def inCommonObjectCache(self, name, key):

        try:
            return key in self.common_objects[name]
        except KeyError:
            return False
    
    def getCommonObject(self, name, key):

        assert self.inCommonObjectCache(name, key)
        
        return self.common_objects[name][key][1]

    def saveToCommonObjectCache(self, name, key, obj, persistent, creation_function):

        name_cd = self.common_objects.setdefault(name, {})

        # Clear out non-persistent objects
        for k, (is_persistent, obj) in name_cd.items():
            if not is_persistent:
                del name_cd[k]

        # This allows creation after the previous one is deleted
        if obj is None:
            assert creation_function is not None
            obj = creation_function()
            
        name_cd[key] = (persistent, obj)

        return obj













class DBWrapper(object):
    """
    A thin wrapper around an sqlalchemy database.
    """
    
    def __init__(self, dbfile):

        # Open the database
        self.engine   = create_engine('sqlite:///' + dbfile)
        self.metadata = MetaData()
        self.metadata.bind = self.engine
        
    def table(self, name, *columns, **kwargs):
        """
        Returns a reference to the table named `name`.  
        """
        t = Table(name, self.metadata, *columns, **kwargs)
        t.create(self.engine, checkfirst=True)
        
        return t
