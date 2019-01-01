import logging

from concurrent import futures
from pymongo import monitoring

from opencensus.trace import execution_context, tracer
from opencensus.trace.ext.pymongo.trace import CommandTracer
from opencensus.trace.propagation import binary_format
from opencensus.trace.tracers.noop_tracer import NoopTracer

log = logging.getLogger(__name__)

MODULE_NAME = 'pymongo_tornado'


def trace_integration(tracer=None):
    """Wrap the pymongo connection to trace it."""
    log.info('Integrated module: {}'.format(MODULE_NAME))
    monitoring.register(CommandTracer())

    # When running Pymongo under Tornado, all commands are run on a different thread pool. In order to get the correct
    # context for the listener, we need to pass the context across the thread boundaries using some of the code from
    # the 'threading' integration. We also could just use the 'threading' integration, but we don't want to start a
    # span for every thread.
    submit_func = getattr(futures.ThreadPoolExecutor, "submit")
    setattr(
        futures.ThreadPoolExecutor,
        submit_func.__name__,
        wrap_submit(submit_func),
    )


def wrap_submit(submit_func):
    """Wrap the apply_async function of multiprocessing.pools. Get the function
    that will be called and wrap it then add the opencensus context."""

    def call(self, func, *args, **kwargs):
        wrapped_func = wrap_task_func(func)
        _tracer = execution_context.get_opencensus_tracer()
        propagator = binary_format.BinaryFormatPropagator()

        wrapped_kwargs = {}
        wrapped_kwargs["span_context_binary"] = propagator.to_header(
            _tracer.span_context
        )
        wrapped_kwargs["kwds"] = kwargs

        if isinstance(_tracer, NoopTracer):
            wrapped_kwargs["noop"] = True
        else:
            wrapped_kwargs["sampler"] = _tracer.sampler
            wrapped_kwargs["exporter"] = _tracer.exporter
            wrapped_kwargs["propagator"] = _tracer.propagator

        return submit_func(self, wrapped_func, *args, **wrapped_kwargs)

    return call


class wrap_task_func(object):
    """Wrap the function given to apply_async to get the tracer from context,
    execute the function then clear the context."""

    def __init__(self, func):
        self.func = func

    def __call__(self, *args, **kwargs):
        kwds = kwargs.pop("kwds")

        span_context_binary = kwargs.pop("span_context_binary")
        propagator = binary_format.BinaryFormatPropagator()
        kwargs["span_context"] = propagator.from_header(span_context_binary)

        _tracer = NoopTracer() if kwargs.get("noop", False) else tracer.Tracer(**kwargs)
        execution_context.set_opencensus_tracer(_tracer)
        result = self.func(*args, **kwds)
        return result
