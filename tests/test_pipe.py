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

import common

import uv


class TestPipe(common.TestCase):
    def test_connect_bad(self):
        def on_connect(request, status):
            self.assert_not_equal(status, uv.StatusCode.SUCCESS)
            request.stream.close()

        self.pipe = uv.Pipe()
        self.pipe.connect(common.BAD_PIPE, on_connect=on_connect)

        self.loop.run()