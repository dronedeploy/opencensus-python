# -*- coding: utf8 -*-
from mock import patch
import unittest

import redis

from opencensus.trace.exporters.capturing_exporter import CapturingExporter
from opencensus.trace import tracer as tracer_module, config_integration
from opencensus.trace.ext.redis.trace import MODULE_NAME
from opencensus.trace.propagation.google_cloud_format import GoogleCloudFormatPropagator
from opencensus.trace.samplers import AlwaysOnSampler


class TestTracing(unittest.TestCase):
    def setUp(self):
        self.exporter = CapturingExporter()
        self.tracer = tracer_module.Tracer(
            sampler=AlwaysOnSampler(),
            exporter=self.exporter,
            propagator=GoogleCloudFormatPropagator()
        )

        config_integration.trace_integrations(['redis'], tracer=self.tracer)

        self.client = redis.StrictRedis()

        # Stash away the original methods for
        # after-test restoration.
        self._execute_command = redis.StrictRedis.execute_command
        self._pipeline = redis.StrictRedis.pipeline

    def tearDown(self):
        redis.StrictRedis.execute_command = self._execute_command
        redis.StrictRedis.pipeline = self._pipeline

    def test_trace_nothing(self):
        with patch.object(self.client,
                          'execute_command') as exc_command:
            exc_command.__name__ = 'execute_command'
            self.client.get('my.key')
            self.assertEqual(exc_command.call_count, 1)
            spans = self.exporter.spans
            self.assertEqual(len(spans), 0)

    def test_trace_all_client(self):
        self.client.get('my.key')
        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        span = spans[0]
        self.assertEqual(span.name, '[{}]{}'.format(MODULE_NAME, 'GET'))
        self.assertEqual(span.attributes, {
            'redis.statement': 'GET my.key',
        })

    def test_trace_unicode_key(self):
        self.client.get(u'my.kèy')
        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        span = spans[0]
        self.assertEqual(span.name, '[{}]{}'.format(MODULE_NAME, 'GET'))
        self.assertEqual(span.attributes, {
            'redis.statement': 'GET my.kèy',
        })

    def test_trace_all_pipeline(self):
        pipe = self.client.pipeline()
        pipe.lpush('my:keys', 1, 3)
        pipe.rpush('my:keys', 5, 7)
        pipe.execute()

        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        span = spans[0]
        self.assertEqual(span.name, '[{}]{}'.format(MODULE_NAME, 'MULTI'))
        self.assertEqual(span.attributes, {
            'redis.statement': 'LPUSH my:keys 1 3;RPUSH my:keys 5 7',
        })

    def test_trace_all_pubsub(self):
        pubsub = self.client.pubsub()
        pubsub.subscribe('test')

        # Subscribing can cause more than a SUBSCRIBE call.
        spans = self.exporter.spans[0]
        self.assertTrue(len(spans) >= 1)
        span = spans[0]
        self.assertEqual(span.name, '[{}]{}'.format(MODULE_NAME, 'SUBSCRIBE'))
        self.assertEqual(span.attributes, {
            'redis.statement': 'SUBSCRIBE test',
        })
