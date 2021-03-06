"""Caches are used for multiple things:

    - To speed up asset building. Filter operations every step
      of the way can be cached, so that individual parts of a
      build that haven't changed can be reused.

    - Bundle definitions are cached when a bundle is built so we
      can determine whether they have changed and whether a rebuild
      is required.

This data is not all stored in the same cache necessarily. The
classes in this module provide the "environment.cache" object, but
also serve in other places.
"""

import os
from os import path
from webassets.merge import BaseHunk
from webassets.filter import Filter, freezedicts
from webassets.utils import md5_constructor, pickle


__all__ = ('FilesystemCache', 'MemoryCache', 'get_cache',)


def make_hashable(data):
    """Ensures ``data`` can be hashed().

    Mostly needs to support dict. The other special types we use
    as hash keys (Hunks, Filters) already have a proper hash() method.

    See also ``make_md5``.

    Note that we do not actually hash the data for the memory cache.
    """
    return freezedicts(data)


def make_md5(data):
    """Make a md5 hash based on``data``.

    Specifically, this knows about ``Hunk`` objects, and makes sure
    the actual content is hashed.

    This is very conservative, and raises an exception if there are
    data types that it does not explicitly support. This is because
    we had in the past some debugging headaches with the cache not
    working for this very reason.

    MD5 is faster than sha, and we don't care so much about collisions.
    We care enough however not to use hash().
    """
    def walk(obj):
        if isinstance(obj, (tuple, list)):
            for item in obj:
                for d in walk(item): yield d
        elif isinstance(obj, dict):
            for k in sorted(obj.keys()):
                for d in walk(k): yield d
                for d in walk(obj[k]): yield d
        elif isinstance(obj, BaseHunk):
            yield obj.data()
        elif isinstance(obj, Filter):
            yield str(hash(obj))
        elif isinstance(obj, (int, basestring)):
            yield str(obj)
        else:
            raise ValueError('Cannot MD5 type %s' % type(obj))
    md5 = md5_constructor()
    for d in walk(data):
        md5.update(d)
    return md5.hexdigest()


def maybe_pickle(value):
    """Pickle the given value if it is not a string."""
    if not isinstance(value, basestring):
        return pickle.dumps(value)
    return value


def safe_unpickle(string):
    """Unpickle the string, or return ``None`` if that fails."""
    try:
        return pickle.loads(string)
    except:
        return None


class BaseCache(object):
    """Abstract base class.

    The cache key must be something that is supported by the Python hash()
    function. The cache value may be a string, or anything that can be pickled.

    Since the cache is used for multiple purposes, all webassets-internal code
    should always tag its keys with an id, like so:

        key = ("tag", actual_key)

    One cache instance can only be used safely with a single Environment.
    """

    def get(self, key, python=None):
        """Should return the cache contents, or False.

        If ``python`` is set, the cache value will be unpickled before it is
        returned. You need this when you passed a non-string value to
        :meth:`set`..
        """
        raise NotImplementedError()

    def set(self, key, value):
        raise NotImplementedError()


class MemoryCache(BaseCache):
    """Caches stuff in the process memory.

    WARNING: Do NOT use this in a production environment, where you
    are likely going to have multiple processes serving the same app!

    Note that the keys are used as-is, not passed through hash() (which is
    a difference: http://stackoverflow.com/a/9022664/15677). However, the
    reason we don't is because the original value is nicer to debug.
    """

    def __init__(self, capacity):
        self.capacity = capacity
        self.keys = []
        self.cache = {}

    def __eq__(self, other):
        """Return equality with the config values that instantiate
        this instance.
        """
        return False == other or \
               None == other or \
               id(self) == id(other)

    def get(self, key, python=None):
        key = make_hashable(key)
        return self.cache.get(key, None)

    def set(self, key, value):
        key = make_hashable(key)
        self.cache[key] = value
        try:
            self.keys.remove(key)
        except ValueError:
            pass
        self.keys.append(key)

        # limit cache to the given capacity
        to_delete = self.keys[0:max(0, len(self.keys)-self.capacity)]
        self.keys = self.keys[len(to_delete):]
        for item in to_delete:
            del self.cache[item]


class FilesystemCache(BaseCache):
    """Uses a temporary directory on the disk.
    """

    def __init__(self, directory):
        self.directory = directory

    def __eq__(self, other):
        """Return equality with the config values
        that instantiate this instance.
        """
        return True == other or \
               self.directory == other or \
               id(self) == id(other)

    def get(self, key, python=None):
        filename = path.join(self.directory, '%s' % make_md5(key))
        if not path.exists(filename):
            return None
        f = open(filename, 'rb')
        try:
            result = f.read()
        finally:
            f.close()

        if python:
            return safe_unpickle(result)
        return result

    def set(self, key, data):
        filename = path.join(self.directory, '%s' % make_md5(key))
        f = open(filename, 'wb')
        try:
            f.write(maybe_pickle(data))
        finally:
            f.close()


def get_cache(option, env):
    """Return a cache instance based on ``option``.
    """
    if not option:
        return None

    if isinstance(option, BaseCache):
        return option
    elif isinstance(option, type) and issubclass(option, BaseCache):
        return option()

    if option is True:
        directory = path.join(env.directory, '.webassets-cache')
        # Auto-create the default directory
        if not path.exists(directory):
            os.makedirs(directory)
    else:
        directory = option
    return FilesystemCache(directory)
