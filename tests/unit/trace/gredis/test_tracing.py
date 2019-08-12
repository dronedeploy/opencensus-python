from gredis.client import AsyncStrictRedis
from tornado.testing import gen_test, AsyncTestCase

from opencensus.trace import tracer as tracer_module, config_integration
from opencensus.trace.exporters.capturing_exporter import CapturingExporter
from opencensus.trace.ext.redis.trace import MODULE_NAME
from opencensus.trace.propagation.google_cloud_format import GoogleCloudFormatPropagator
from opencensus.trace.samplers import AlwaysOnSampler


class TestTracing(AsyncTestCase):

    def setUp(self):
        super(TestTracing, self).setUp()
        self.exporter = CapturingExporter()
        self.tracer = tracer_module.Tracer(
            sampler=AlwaysOnSampler(),
            exporter=self.exporter,
            propagator=GoogleCloudFormatPropagator()
        )

        config_integration.trace_integrations(['gredis'], tracer=self.tracer)

        self.client = AsyncStrictRedis()

    @gen_test
    def test_trace_nothing(self):
        yield self.client.get('my.key')
        spans = self.exporter.spans
        self.assertEqual(len(spans), 1)

    @gen_test
    def test_trace_all_client(self):
        yield self.client.get('my.key')
        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        span = spans[0]
        self.assertEqual(span.name, '[{}]{}'.format(MODULE_NAME, 'GET'))
        self.assertEqual(span.attributes, {
            'redis.statement': 'GET my.key',
        })

    @gen_test
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
