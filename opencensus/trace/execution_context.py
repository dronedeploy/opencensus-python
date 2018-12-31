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

import threading

from opencensus.trace.tracers import noop_tracer

_thread_local = threading.local()


def _get_context():
    return _thread_local


def get_opencensus_tracer():
    """Get the opencensus tracer from thread local."""
    return getattr(_get_context(), 'tracer', noop_tracer.NoopTracer())


def set_opencensus_tracer(tracer):
    """Add the tracer to thread local."""
    setattr(_get_context(), 'tracer', tracer)


def set_opencensus_attr(attr_key, attr_value):
    # If there is no attrs, initialize it to empty dict.
    attrs = getattr(_get_context(), 'attrs', {})

    attrs[attr_key] = attr_value

    setattr(_get_context(), 'attrs', attrs)


def set_opencensus_attrs(attrs):
    setattr(_get_context(), 'attrs', attrs)


def get_opencensus_attr(attr_key):
    attrs = getattr(_get_context(), 'attrs', None)

    if attrs is not None:
        return attrs.get(attr_key)

    return None


def get_opencensus_attrs():
    return getattr(_get_context(), 'attrs', None)


def get_current_span():
    return getattr(_get_context(), 'current_span', None)


def set_current_span(current_span):
    setattr(_get_context(), 'current_span', current_span)


def get_opencensus_full_context():
    _tracer = get_opencensus_tracer()
    _span = get_current_span()
    _attrs = get_opencensus_attrs()
    return _tracer, _span, _attrs


def set_opencensus_full_context(tracer, span, attrs):
    set_opencensus_tracer(tracer)
    set_current_span(span)
    if not attrs:
        set_opencensus_attrs({})
    else:
        set_opencensus_attrs(attrs)


def clean():
    setattr(_get_context(), 'attrs', {})
    if hasattr(_get_context(), 'current_span'):
        delattr(_get_context(), 'current_span')
    if hasattr(_get_context(), 'tracer'):
        delattr(_get_context(), 'tracer')


def clear():
    """Clear the thread local, used in test."""
    _get_context().__dict__.clear()
