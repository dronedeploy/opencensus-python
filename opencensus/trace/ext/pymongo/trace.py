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
import json
import logging

import six
from pymongo import monitoring

from opencensus.trace import execution_context
from opencensus.trace import span as span_module

log = logging.getLogger(__name__)

MODULE_NAME = 'pymongo'


def trace_integration(tracer=None):
    """Wrap the pymongo connection to trace it."""
    log.info('Integrated module: {}'.format(MODULE_NAME))
    monitoring.register(CommandTracer())


class CommandTracer(monitoring.CommandListener):

    def started(self, event):
        tracer = execution_context.get_opencensus_tracer()
        span = tracer.start_span('{}.{}'.format(MODULE_NAME, event.command_name))
        span.span_kind = span_module.SpanKind.CLIENT
        tracer.add_attribute_to_current_span('{}.db'.format(MODULE_NAME), event.database_name)
        _set_query_metadata(event)

    def succeeded(self, event):
        tracer = execution_context.get_opencensus_tracer()
        tracer.end_span()

    def failed(self, event):
        tracer = execution_context.get_opencensus_tracer()
        tracer.end_span()

# Borrowed from https://github.com/DataDog/dd-trace-py/blob/master/ddtrace/contrib/pymongo/parse.py

def _set_query_metadata(event):
    tracer = execution_context.get_opencensus_tracer()
    name, db, coll, query = _parse_spec(event.command)
    if not coll:
        return

    tracer.add_attribute_to_current_span('{}.collection'.format(MODULE_NAME), coll)
    if query:
        nq = _normalize_filter(query)
        q = json.dumps(nq)
        value = '{} {} {}'.format(name, coll, q)
    else:
        value = '{} {}'.format(name, coll)
    tracer.add_attribute_to_current_span('{}.query'.format(MODULE_NAME), value)


def _parse_spec(spec, db=None):
    """ Return a Command that has parsed the relevant detail for the given
        pymongo SON spec.
    """
    try:
        items = list(spec.items())
    except TypeError:
        return None, None, None, None

    if not items:
        return None, None, None, None
    name, coll = items[0]

    query = None
    if name == 'update':
        updates = spec.get('updates')
        if updates:
            query = updates[0].get("q")

    elif name == 'find':
        filter = spec.get('filter')
        if filter:
            query = filter

    elif name == 'delete':
        dels = spec.get('deletes')
        if dels:
            query = dels[0].get("q")

    return name, db, coll, query


def _normalize_filter(f=None):
    if f is None:
        return {}
    elif isinstance(f, list):
        # normalize lists of filters
        # e.g. {$or: [ { age: { $lt: 30 } }, { type: 1 } ]}
        return [_normalize_filter(s) for s in f]
    elif isinstance(f, dict):
        # normalize dicts of filters
        #   {$or: [ { age: { $lt: 30 } }, { type: 1 } ]})
        out = {}
        for k, v in six.iteritems(f):
            if k == "$in" or k == "$nin":
                # special case $in queries so we don't loop over lists.
                out[k] = "?"
            elif isinstance(v, list) or isinstance(v, dict):
                out[k] = _normalize_filter(v)
            else:
                out[k] = '?'
        return out
    else:
        return {}

