from mock import patch
import unittest

import redis

from opencensus.trace import tracer as tracer_module, config_integration
from opencensus.trace.exporters.capturing_exporter import CapturingExporter
from opencensus.trace.ext.redis.trace import MODULE_NAME
from opencensus.trace.propagation.google_cloud_format import GoogleCloudFormatPropagator
from opencensus.trace.samplers import AlwaysOnSampler


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.exporter = CapturingExporter()
        self.tracer = tracer_module.Tracer(
            sampler=AlwaysOnSampler(),
            exporter=self.exporter,
            propagator=GoogleCloudFormatPropagator()
        )
        config_integration.trace_integrations(['redis'], tracer=self.tracer)
        self.client = redis.StrictRedis()

    def test_trace_pipeline(self):
        pipe = self.client.pipeline()
        pipe.lpush('my:keys', 1, 3)
        pipe.lpush('my:keys', 5, 7)
        pipe.execute()

        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].name, '[{}]{}'.format(MODULE_NAME, 'MULTI'))
        self.assertEqual(spans[0].attributes, {
            'redis.statement': 'LPUSH ? ? ?;LPUSH ? ? ?',
        })

    def test_trace_pipeline_empty(self):
        pipe = self.client.pipeline()
        pipe.execute()
        spans = self.exporter.spans
        self.assertEqual(len(spans), 0)

    def test_trace_pipeline_immediate(self):
        pipe = self.client.pipeline()
        pipe.immediate_execute_command('WATCH', 'my:key')
        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        span = spans[0]
        self.assertEqual(span.name, '[{}]{}'.format(MODULE_NAME, 'WATCH'))
        self.assertEqual(span.attributes, {
            'redis.statement': 'WATCH ?',
        })

    def test_trace_pipeline_error(self):
        pipe = self.client.pipeline()
        pipe.lpush('my:keys', 1, 3)
        pipe.lpush('my:keys', 5, 7)

        call_exc = None
        try:
            pipe.execute()
        except ValueError as exc:
            call_exc = exc

        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        span = spans[0]
        self.assertEqual(span.name, '[{}]{}'.format(MODULE_NAME, 'MULTI'))
        self.assertEqual(span.attributes, {
            'redis.statement': 'LPUSH ? ? ?;LPUSH ? ? ?',
        })
