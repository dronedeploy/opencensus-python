from mock import patch
import unittest

import redis

from opencensus.trace import tracer as tracer_module, config_integration
from opencensus.trace.exporters.capturing_exporter import CapturingExporter
from opencensus.trace.propagation.google_cloud_format import GoogleCloudFormatPropagator
from opencensus.trace.samplers import AlwaysOnSampler


class TestPubSub(unittest.TestCase):

    def setUp(self):
        self.exporter = CapturingExporter()
        self.tracer = tracer_module.Tracer(
            sampler=AlwaysOnSampler(),
            exporter=self.exporter,
            propagator=GoogleCloudFormatPropagator()
        )

        config_integration.trace_integrations(['redis'], tracer=self.tracer)
        self.client = redis.StrictRedis()

    def test_trace_pubsub(self):
        pubsub = self.client.pubsub()
        pubsub.subscribe('test')
        pubsub.get_message()
        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].name, '[redis]SUBSCRIBE')
        self.assertEqual(spans[0].attributes, {
            'redis.statement': 'SUBSCRIBE ?',
        })

    def test_trace_pubsub_execute_command(self):
        pubsub = self.client.pubsub()
        pubsub.execute_command('GET', 'foo')
        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].name, '[redis]GET')
        self.assertEqual(spans[0].attributes, {
            'redis.statement': 'GET ?',
        })
