# -*- coding: utf-8 -*-
#
# Copyright (C) 2015, Maximilian Köhl <mail@koehlma.de>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import threading

from common import TestCase

import uv


class TestAsync(TestCase):
    def test_async(self):
        def on_wakeup(async):
            self.async_called = True
            async.close()
            self.assert_equal(self.loop_thread, threading.current_thread)

        def on_prepare(prepare):
            threading.Thread(target=self.async.send).start()
            prepare.close()

        self.async_called = False
        self.loop_thread = threading.current_thread

        self.async = uv.Async(on_wakeup=on_wakeup)

        self.prepare = uv.Prepare(on_prepare=on_prepare)
        self.prepare.start()

        self.loop.run()

        self.assert_true(self.async_called)
