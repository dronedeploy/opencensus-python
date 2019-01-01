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
import importlib
import logging

import six
import wrapt
from tornado.web import HTTPError

from opencensus.trace import attributes_helper, execution_context
from opencensus.trace import span as span_module
from opencensus.trace import tracer as tracer_module
from opencensus.trace.ext import utils
from opencensus.trace.ext.tornado.stack_context import tracer_stack_context, _TracerRequestContextManager
from opencensus.trace.ext.utils import DEFAULT_BLACKLIST_PATHS
from opencensus.trace.tracers.noop_tracer import NoopTracer

log = logging.getLogger(__name__)

CONFIG_KEY = 'opencensus.tracer'
SAMPLER_KEY = 'opencensus.tracer.SAMPLER'
EXPORTER_KEY = 'opencensus.tracer.EXPORTER'
PROPAGATOR_KEY = 'opencensus.tracer.PROPAGATOR'
BLACKLIST_PATHS = 'opencensus.tracer.ext.BLACKLIST_PATHS'

DEFAULT_TORNADO_TRACER_CONFIG = {
    SAMPLER_KEY: 'opencensus.trace.samplers.always_on.AlwaysOnSampler',
    EXPORTER_KEY: 'opencensus.trace.exporters.print_exporter.PrintExporter',
    PROPAGATOR_KEY: 'opencensus.trace.propagation.google_cloud_format.GoogleCloudFormatPropagator',
    BLACKLIST_PATHS: DEFAULT_BLACKLIST_PATHS,
}

HTTP_METHOD = attributes_helper.COMMON_ATTRIBUTES['HTTP_METHOD']
HTTP_URL = attributes_helper.COMMON_ATTRIBUTES['HTTP_URL']
HTTP_STATUS_CODE = attributes_helper.COMMON_ATTRIBUTES['HTTP_STATUS_CODE']

TRACER = "opencensus.trace.ext.tornado.Tracer"

MODULE_NAME = 'tornado.web'


def trace_integration(tracer=None):
    log.info('Integrated module: {}'.format(MODULE_NAME))
    trace_tornado()


def trace_tornado():
    wrapt.wrap_function_wrapper(MODULE_NAME, 'Application.__init__', _init)
    wrapt.wrap_function_wrapper(MODULE_NAME, 'RequestHandler._execute', _execute)
    wrapt.wrap_function_wrapper(MODULE_NAME, 'RequestHandler.on_finish', _on_finish)
    wrapt.wrap_function_wrapper(MODULE_NAME, 'RequestHandler.log_exception', _log_exception)

    # We need to replace OpenCensus' default execution context with variables that can be managed via
    # Tornado's StackContext as opposed to a thread local
    setattr(execution_context, '_get_context', _get_context)


def _get_context():
    context = _TracerRequestContextManager.current_context()
    if context is None:
        return execution_context._thread_local
    return context


def _init(__init__, app, args, kwargs):
    __init__(*args, **kwargs)
    config = app.settings.get(CONFIG_KEY, DEFAULT_TORNADO_TRACER_CONFIG)
    processed_config = {
        PROPAGATOR_KEY: _obj_or_import(config[PROPAGATOR_KEY]),
        EXPORTER_KEY: _obj_or_import(config[EXPORTER_KEY]),
        SAMPLER_KEY: _obj_or_import(config[SAMPLER_KEY]),
        BLACKLIST_PATHS: config[BLACKLIST_PATHS],
    }
    app.settings[CONFIG_KEY] = processed_config


def _obj_or_import(obj):
    """If the the config value is a string, then instantiate it as a class otherwise just return the object
    """
    return _convert_to_import(obj)() if isinstance(obj, six.string_types) else obj


def _convert_to_import(path):
    """Given a string which represents the import path, convert to the
    class to import.
    """
    # Split the path string to module name and class name
    try:
        module_name, class_name = path.rsplit('.', 1)
        module = importlib.import_module(module_name)
        return getattr(module, class_name)
    except (ImportError, AttributeError):
        msg = 'Failed to import {}'.format(path)
        log.error(msg)

        raise ImportError(msg)


def _execute(func, handler, args, kwargs):
    with tracer_stack_context():
        config = handler.settings.get(CONFIG_KEY, None)
        if not config or utils.disable_tracing_url(handler.request.path, config[BLACKLIST_PATHS]):
            tracer = NoopTracer()
            setattr(handler.request, TRACER, tracer)
            return func(*args, **kwargs)

        propagator = config[PROPAGATOR_KEY]
        span_context = propagator.from_headers(handler.request.headers)

        tracer = tracer_module.Tracer(
            span_context=span_context,
            sampler=config[SAMPLER_KEY],
            exporter=config[EXPORTER_KEY],
            propagator=propagator)

        setattr(handler.request, TRACER, tracer)
        span = tracer.start_span()
        span.name = '[{}]{}'.format(_get_class_name(handler), handler.request.method)
        span.span_kind = span_module.SpanKind.SERVER
        tracer.add_attribute_to_current_span(
            attribute_key=HTTP_METHOD,
            attribute_value=handler.request.method)
        tracer.add_attribute_to_current_span(
            attribute_key=HTTP_URL,
            attribute_value=handler.request.path)

        return func(*args, **kwargs)


def _on_finish(func, handler, args, kwargs):
    tracer = getattr(handler.request, TRACER, None)
    if not tracer:
        return func(*args, **kwargs)

    delattr(handler.request, TRACER)

    tracer.add_attribute_to_current_span(
        attribute_key=HTTP_STATUS_CODE,
        attribute_value=str(handler.get_status()))
    tracer.finish()
    execution_context.clean()
    return func(*args, **kwargs)


def _log_exception(func, handler, args, kwargs):
    value = args[1] if len(args) == 3 else None
    if value is None:
        return func(*args, **kwargs)

    tracer = getattr(handler.request, TRACER, None)
    if not tracer:
        return func(*args, **kwargs)

    delattr(handler.request, TRACER)

    if not isinstance(value, HTTPError) or 500 <= value.status_code <= 599:
        tracer.add_attribute_to_current_span(
            attribute_key=HTTP_STATUS_CODE,
            attribute_value=str(handler.get_status()))
        tracer.finish()
        execution_context.clean()

    return func(*args, **kwargs)


def _get_class_name(obj):
    """Return a name which includes the module name and class name."""
    class_name = getattr(obj, '__name__', obj.__class__.__name__)
    module_name = obj.__module__

    if module_name is not None:
        return '{}.{}'.format(module_name, class_name)
    return class_name
