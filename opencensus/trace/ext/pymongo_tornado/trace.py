# Copyright 2017, OpenCensus Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging

from pymongo import monitoring
from tornado.ioloop import IOLoop

from opencensus.trace.ext.pymongo.trace import CommandTracer

log = logging.getLogger(__name__)

MODULE_NAME = 'motor_tornado'


def trace_integration(tracer=None):
    """Wrap the pymongo connection to trace it."""
    log.info('Integrated module: {}'.format(MODULE_NAME))
    monitoring.register(TornadoCommandTracer())


class TornadoCommandTracer(CommandTracer):

    def started(self, event):
        IOLoop.instance().add_callback(lambda: super(TornadoCommandTracer, self).started(event))

    def succeeded(self, event):
        IOLoop.instance().add_callback(lambda: super(TornadoCommandTracer, self).succeeded(event))

    def failed(self, event):
        IOLoop.instance().add_callback(lambda: super(TornadoCommandTracer, self).failed(event))
