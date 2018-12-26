from mock import patch
import unittest

import redis

from opencensus.trace import tracer as tracer_module, config_integration
from opencensus.trace.exporters.capturing_exporter import CapturingExporter
from opencensus.trace.ext.redis.trace import MODULE_NAME
from opencensus.trace.propagation.google_cloud_format import GoogleCloudFormatPropagator
from opencensus.trace.samplers import AlwaysOnSampler


class TestClient(unittest.TestCase):
    def setUp(self):
        self.exporter = CapturingExporter()
        self.tracer = tracer_module.Tracer(
            sampler=AlwaysOnSampler(),
            exporter=self.exporter,
            propagator=GoogleCloudFormatPropagator()
        )
        config_integration.trace_integrations(['redis'], tracer=self.tracer)
        self.client = redis.StrictRedis()

    def test_trace_client(self):
        self.client.get('my.key')

        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        span = spans[0]
        self.assertEqual(spans[0].name, '[{}]{}'.format(MODULE_NAME, 'GET'))
        self.assertEqual(span.attributes, {
            'redis.statement': 'GET my.key',
        })

    def test_trace_client_pipeline(self):
        pipe = self.client.pipeline()
        pipe.rpush('my:keys', 1, 3)
        pipe.rpush('my:keys', 5, 7)
        pipe.execute()
        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        span = spans[0]
        self.assertEqual(spans[0].name, '[{}]{}'.format(MODULE_NAME, 'MULTI'))
        self.assertEqual(span.attributes, {
            'redis.statement': 'RPUSH my:keys 1 3;RPUSH my:keys 5 7',
        })

    def test_trace_client_pubsub(self):
        pubsub = self.client.pubsub()
        pubsub.subscribe('test')

        # Subscribing can cause more than a SUBSCRIBE call.
        spans = self.exporter.spans[0]
        self.assertTrue(len(spans) >= 1)
        span = spans[0]
        self.assertEqual(spans[0].name, '[{}]{}'.format(MODULE_NAME, 'SUBSCRIBE'))
        self.assertEqual(span.attributes, {
            'redis.statement': 'SUBSCRIBE test',
        })
