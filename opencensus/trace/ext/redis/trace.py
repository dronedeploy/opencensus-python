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
from functools import wraps

import redis

from opencensus.trace import execution_context
from opencensus.trace import span as span_module

log = logging.getLogger(__name__)

MODULE_NAME = 'redis'


def trace_integration(tracer=None):
    """Wrap the pymongo connection to trace it."""
    log.info('Integrated module: {}'.format(MODULE_NAME))
    _patch_redis_classes()


def _normalize_stmt(args):
    return ' '.join([str(arg) for arg in args])


def _normalize_stmts(command_stack):
    commands = [_normalize_stmt(command[0]) for command in command_stack]
    return ';'.join(commands)


def _set_base_span_tags(span, stmt):
    span.span_kind = span_module.SpanKind.CLIENT
    span.add_attribute('{}.statement'.format(MODULE_NAME), stmt)


def _patch_redis_classes():
    # Patch the outgoing commands.
    _patch_obj_execute_command(redis.StrictRedis, True)

    # Patch the created pipelines.
    pipeline_method = redis.StrictRedis.pipeline

    @wraps(pipeline_method)
    def tracing_pipeline(self, transaction=True, shard_hint=None):
        pipe = pipeline_method(self, transaction, shard_hint)
        _patch_pipe_execute(pipe)
        return pipe

    redis.StrictRedis.pipeline = tracing_pipeline

    # Patch the created pubsubs.
    pubsub_method = redis.StrictRedis.pubsub

    @wraps(pubsub_method)
    def tracing_pubsub(self, **kwargs):
        pubsub = pubsub_method(self, **kwargs)
        _patch_pubsub(pubsub)
        return pubsub

    redis.StrictRedis.pubsub = tracing_pubsub


def _patch_client(client):
    # Patch the outgoing commands.
    _patch_obj_execute_command(client)

    # Patch the created pipelines.
    pipeline_method = client.pipeline

    @wraps(pipeline_method)
    def tracing_pipeline(transaction=True, shard_hint=None):
        pipe = pipeline_method(transaction, shard_hint)
        _patch_pipe_execute(pipe)
        return pipe

    client.pipeline = tracing_pipeline

    # Patch the created pubsubs.
    pubsub_method = client.pubsub

    @wraps(pubsub_method)
    def tracing_pubsub(**kwargs):
        pubsub = pubsub_method(**kwargs)
        _patch_pubsub(pubsub)
        return pubsub

    client.pubsub = tracing_pubsub


def _patch_pipe_execute(pipe):
    tracer = execution_context.get_opencensus_tracer()

    # Patch the execute() method.
    execute_method = pipe.execute

    @wraps(execute_method)
    def tracing_execute(raise_on_error=True):
        if not pipe.command_stack:
            # Nothing to process/handle.
            return execute_method(raise_on_error=raise_on_error)

        with tracer.start_span('[{}]MULTI'.format(MODULE_NAME)) as span:
            _set_base_span_tags(span, _normalize_stmts(pipe.command_stack))
            res = execute_method(raise_on_error=raise_on_error)

        return res

    pipe.execute = tracing_execute

    # Patch the immediate_execute_command() method.
    immediate_execute_method = pipe.immediate_execute_command

    @wraps(immediate_execute_method)
    def tracing_immediate_execute_command(*args, **options):
        command = args[0]
        with tracer.start_span('[{}]{}'.format(MODULE_NAME, command)) as span:
            _set_base_span_tags(span, _normalize_stmt(args))
            immediate_execute_method(*args, **options)

    pipe.immediate_execute_command = tracing_immediate_execute_command


def _patch_pubsub(pubsub):
    _patch_pubsub_parse_response(pubsub)
    _patch_obj_execute_command(pubsub)


def _patch_pubsub_parse_response(pubsub):
    tracer = execution_context.get_opencensus_tracer()

    # Patch the parse_response() method.
    parse_response_method = pubsub.parse_response

    @wraps(parse_response_method)
    def tracing_parse_response(block=True, timeout=0):
        with tracer.start_span('[{}]{}'.format(MODULE_NAME, 'SUB')) as span:
            _set_base_span_tags(span, '')
            rv = parse_response_method(block=block, timeout=timeout)

        return rv

    pubsub.parse_response = tracing_parse_response


def _patch_obj_execute_command(redis_obj, is_klass=False):
    tracer = execution_context.get_opencensus_tracer()

    execute_command_method = redis_obj.execute_command

    @wraps(execute_command_method)
    def tracing_execute_command(*args, **kwargs):
        if is_klass:
            # Unbound method, we will get 'self' in args.
            reported_args = args[1:]
        else:
            reported_args = args

        command = reported_args[0]

        with tracer.start_span('[{}]{}'.format(MODULE_NAME, command)) as span:
            _set_base_span_tags(span, _normalize_stmt(reported_args))
            rv = execute_command_method(*args, **kwargs)

        return rv

    redis_obj.execute_command = tracing_execute_command


