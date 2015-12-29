# -*- coding: utf-8 -*-

# Copyright (C) 2015, Maximilian Köhl <mail@koehlma.de>
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Lesser General Public License version 3 as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
# PARTICULAR PURPOSE. See the GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License along
# with this program. If not, see <http://www.gnu.org/licenses/>.

from __future__ import print_function, unicode_literals, division, absolute_import

import abc
import sys
import threading
import traceback

from . import common, error, library
from .library import ffi, lib

__all__ = ['RunMode', 'Loop']


class RunMode(common.Enumeration):
    DEFAULT = lib.UV_RUN_DEFAULT
    ONCE = lib.UV_RUN_ONCE
    NOWAIT = lib.UV_RUN_NOWAIT


def default_excepthook(loop, exc_type, exc_value, exc_traceback):
    print('Exception happened during callback execution!', file=sys.stderr)
    traceback.print_exception(exc_type, exc_value, exc_traceback)
    loop.stop()


class Allocator(common.with_metaclass(abc.ABCMeta)):
    uv_alloc_cb = None

    @abc.abstractmethod
    def finalize(self, uv_handle, length, uv_buf): pass


class DefaultAllocator(Allocator):
    def __init__(self, buffer_size=2**16):
        self.buffer_size = buffer_size
        self.buffer_in_use = False
        self.c_buffer = ffi.new('char[]', self.buffer_size)
        self.uv_alloc_cb = ffi.callback('uv_alloc_cb', self._allocate)

    def _allocate(self, uv_handle, suggested_size, uv_buf):
        if self.buffer_in_use:
            library.uv_buffer_set(uv_buf, ffi.NULL, 0)
        else:
            library.uv_buffer_set(uv_buf, self.c_buffer, self.buffer_size)
        self.buffer_in_use = True

    def finalize(self, uv_handle, length, uv_buf):
        self.buffer_in_use = False
        c_base = library.uv_buffer_get_base(uv_buf)
        return bytes(ffi.buffer(c_base, length)) if length > 0 else b''


class Loop(object):
    _global_lock = threading.Lock()
    _thread_locals = threading.local()
    _default = None
    _loops = set()

    @classmethod
    def get_default(cls, instantiate=True, **arguments):
        """
        :param instantiate:
        :type instantiate: bool
        :return: global default loop
        :rtype: Loop
        """
        with cls._global_lock:
            if cls._default is None and instantiate:
                Loop._default = Loop(default=True, **arguments)
            return Loop._default

    @classmethod
    def get_current(cls, instantiate=True, **arguments):
        """
        :param instantiate:
        :type instantiate: bool
        :return: current threads default loop
        :rtype: Loop
        """
        loop = getattr(cls._thread_locals, 'loop', None)
        if loop is None and instantiate: return cls(**arguments)
        return loop

    @classmethod
    def get_loops(cls):
        """
        :return:
        :rtype: frozenset[Loop]
        """
        with cls._global_lock: return frozenset(cls._loops)

    def __init__(self, allocator=None, default=False, buffer_size=2**16):
        if default:
            assert Loop._default is None
            self.uv_loop = lib.uv_default_loop()
            if not self.uv_loop: raise RuntimeError('error initializing default loop')
        else:
            self.uv_loop = ffi.new('uv_loop_t*')
            code = lib.uv_loop_init(self.uv_loop)
            if code < 0: raise error.UVError(code)

        self.attachment = library.attach(self.uv_loop, self)

        self.allocator = allocator or DefaultAllocator(buffer_size)

        self.excepthook = default_excepthook
        """
        If an exception occurs during the execution of a callback this
        excepthook is called with the corresponding event loop and
        exception details. The default behavior is to print the
        traceback to stderr and stop the event loop. To override the
        default behavior assign a custom function to this attribute.

        .. note::
            If the excepthook raises an exception itself the program
            would be in an undefined state. Therefore it terminates
            with `sys.exit(1)` in that case immediately.


        .. function:: excepthook(loop, exc_type, exc_value, exc_traceback)

            :param loop:
                corresponding event loop
            :param exc_type:
                exception type (subclass of :class:`BaseException`)
            :param exc_value:
                exception instance
            :param exc_traceback:
                traceback which encapsulates the call stack at the
                point where the exception originally occurred

            :type loop:
                uv.Loop
            :type exc_type:
                type
            :type exc_value:
                BaseException
            :type exc_traceback:
                traceback


        :readonly:
            False
        :type:
            ((uv.Loop, type, Exception, traceback.Traceback) -> None) |
            ((Any, uv.Loop, type, Exception, traceback.Traceback) -> None)
        """
        self.exc_type = None
        """
        Type of last exception handled by excepthook.

        :readonly:
            True
        :type:
            type
        """
        self.exc_value = None
        """
        Instance of last exception handled by excepthook.

        :readonly:
            True
        :type:
            BaseException
        """
        self.exc_traceback = None
        """
        Traceback which encapsulates the call stack at the point where
        the last exception handled by excepthook originally occurred.

        :readonly:
            True
        :type:
            traceback
        """
        self.handles = set()
        """
        Contains all handles running on this loop which have not already
        been closed. We have to keep references to every single handle in
        this set because otherwise they are garbage collected before they
        have been closed which leads to segmentation faults.

        :readonly: True
        :type: set[Handle]
        """
        self.requests = set()
        """
        Contains all requests running on this loop which are not already
        finished. We have to keep references to every single request in
        this set because otherwise they are garbage collected before they
        are finished which leads to segmentation faults.

        :readonly: True
        :type: set[Handle]
        """
        self.closed = False
        """
        Loop has been closed. This is `True` right after close has been
        called. It means all internal resources are freed and this loop
        is ready to be garbage collected. Operations on a closed loop
        will raise :class:`uv.LoopClosedError`.

        :readonly: True
        :type: bool
        """
        with Loop._global_lock: Loop._loops.add(self)
        self.make_current()

    @property
    def alive(self):
        if self.closed: return False
        return bool(lib.uv_loop_alive(self.uv_loop))

    @property
    def now(self):
        if self.closed: raise error.LoopClosedError()
        return lib.uv_now(self.uv_loop)

    def fileno(self):
        if self.closed: raise error.LoopClosedError()
        return lib.uv_backend_fd(self.uv_loop)

    def make_current(self):
        Loop._thread_locals.loop = self

    def update_time(self):
        if self.closed: raise error.LoopClosedError()
        return lib.uv_update_time(self.uv_loop)

    def get_timeout(self):
        if self.closed: raise error.LoopClosedError()
        return lib.uv_backend_timeout(self.uv_loop)

    def run(self, mode=RunMode.DEFAULT):
        if self.closed: raise error.LoopClosedError()
        self.make_current()
        result = bool(lib.uv_run(self.uv_loop, mode))
        return result

    def stop(self):
        if self.closed: return
        lib.uv_stop(self.uv_loop)

    def close(self):
        if self.closed: return
        code = lib.uv_loop_close(self.uv_loop)
        if code < 0: raise error.UVError(code)
        self.uv_loop = None
        self.closed = True
        with Loop._global_lock: Loop._loops.remove(self)
        if Loop._thread_locals.loop is self: Loop._thread_locals.loop = None

    def close_all_handles(self, callback=None):
        for handle in self.handles: handle.close(callback)

    def handle_exception(self):
        self.exc_type, self.exc_value, self.exc_traceback = sys.exc_info()
        try:
            self.excepthook(self, self.exc_type, self.exc_value, self.exc_traceback)
        except:
            # this should never happen during normal operation but if it does the
            # program would be in an undefined state, so exit immediately
            try:
                print('[CRITICAL] error while executing excepthook!')
                traceback.print_exc()
            finally:
                sys.exit(1)
