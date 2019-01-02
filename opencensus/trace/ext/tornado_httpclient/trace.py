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
import functools
import logging

import wrapt
from tornado import stack_context
from tornado.httpclient import HTTPRequest, HTTPError

from opencensus.trace import execution_context, attributes_helper
from opencensus.trace import span as span_module

log = logging.getLogger(__name__)

MODULE_NAME = 'tornado.http_client'

ERROR_MESSAGE = attributes_helper.COMMON_ATTRIBUTES['ERROR_MESSAGE']
HTTP_METHOD = attributes_helper.COMMON_ATTRIBUTES['HTTP_METHOD']
HTTP_URL = attributes_helper.COMMON_ATTRIBUTES['HTTP_URL']
HTTP_STATUS_CODE = attributes_helper.COMMON_ATTRIBUTES['HTTP_STATUS_CODE']


def trace_integration(tracer=None):
    log.info('Integrated module: {}'.format(MODULE_NAME))

    if tracer is not None:
        # The execution_context tracer should never be None - if it has not
        # been set it returns a no-op tracer. Most code in this library does
        # not handle None being used in the execution context.
        execution_context.set_opencensus_tracer(tracer)

    trace_tornado_httpclient()


def trace_tornado_httpclient():
    wrapt.wrap_function_wrapper('tornado.httpclient', 'AsyncHTTPClient.fetch', _fetch_async)


def _normalize_request(args, kwargs):
    req = args[0]
    if not isinstance(req, str):
        # Not a string, no need to force the creation of a HTTPRequest
        return (args, kwargs)

    # keep the original kwargs for calling fetch()
    new_kwargs = {}
    for param in ('callback', 'raise_error'):
        if param in kwargs:
            new_kwargs[param] = kwargs.pop(param)

    req = HTTPRequest(req, **kwargs)
    new_args = [req]
    new_args.extend(args[1:])

    # return the normalized args/kwargs
    return (new_args, new_kwargs)


def _fetch_async(func, handler, args, kwargs):
    # Return immediately if disabled, no args were provided (error)
    # or original_request is set (meaning we are in a redirect step).
    if len(args) == 0 or hasattr(args[0], 'original_request'):
        return func(*args, **kwargs)

    # Force the creation of a HTTPRequest object if needed,
    # so we can inject the context into the headers.
    args, kwargs = _normalize_request(args, kwargs)
    request = args[0]

    tracer = execution_context.get_opencensus_tracer()

    if not isinstance(request, HTTPRequest):
        request = HTTPRequest(url=request, **kwargs)
        args[0] = request

    try:
        headers = tracer.propagator.to_headers(tracer.span_context)
        user_headers = request.headers
        if user_headers:
            headers.update(user_headers)
        request.headers = headers
    except Exception:  # pragma: NO COVER
        pass

    span = tracer.start_span('[tornado.http_client]{}'.format(request.method))
    span.span_kind = span_module.SpanKind.CLIENT

    # Add the requests url to attributes
    tracer.add_attribute_to_current_span(HTTP_URL, request.url)

    future = func(*args, **kwargs)

    # Finish the Span when the Future is done, making
    # sure the StackContext is restored (it's not by default).
    callback = stack_context.wrap(functools.partial(_finish_tracing_callback))
    future.add_done_callback(callback)

    return future


def _finish_tracing_callback(future):
    tracer = execution_context.get_opencensus_tracer()
    status_code = None
    exc = future.exception()
    if exc:
        error = True
        if isinstance(exc, HTTPError):
            status_code = exc.code
            if status_code < 500:
                error = False
        if error:
            tracer.add_attribute_to_current_span(ERROR_MESSAGE, str(exc.message))
    else:
        status_code = future.result().code

    if status_code is not None:
        tracer.add_attribute_to_current_span(
            HTTP_STATUS_CODE, str(status_code))

    tracer.end_span()
