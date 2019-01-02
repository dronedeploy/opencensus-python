import tornado
import tornado.testing
import tornado.web
from tornado.httpclient import HTTPRequest

from opencensus.trace import config_integration, attributes_helper, execution_context
from opencensus.trace import span as span_module
from opencensus.trace import tracer as tracer_module
from opencensus.trace.exporters.capturing_exporter import CapturingExporter
from opencensus.trace.ext.tornado.stack_context import tracer_stack_context
from opencensus.trace.propagation.google_cloud_format import GoogleCloudFormatPropagator
from opencensus.trace.samplers import AlwaysOnSampler

HTTP_METHOD = attributes_helper.COMMON_ATTRIBUTES['HTTP_METHOD']
HTTP_URL = attributes_helper.COMMON_ATTRIBUTES['HTTP_URL']
HTTP_STATUS_CODE = attributes_helper.COMMON_ATTRIBUTES['HTTP_STATUS_CODE']


config_integration.trace_integrations(['tornado_httpclient'])


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        assert self.request.headers.get('X-Cloud-Trace-Context')
        self.write('{}')


class ErrorHandler(tornado.web.RequestHandler):
    def get(self):
        raise ValueError('invalid input')

    def post(self):
        raise ValueError('invalid input')


def app():
    settings = {}
    app = tornado.web.Application(
        [
            ('/', MainHandler),
            ('/error', ErrorHandler),
        ],
        **settings
    )
    return app


class TestClient(tornado.testing.AsyncHTTPTestCase):

    def setUp(self):
        super(TestClient, self).setUp()
        self.exporter = CapturingExporter()
        self.tracer = tracer_module.Tracer(
            sampler=AlwaysOnSampler(),
            exporter=self.exporter,
            propagator=GoogleCloudFormatPropagator()
        )

        self.stack_context = tracer_stack_context()
        self.stack_context.__enter__()
        execution_context.set_opencensus_tracer(self.tracer)

    def tearDown(self):
        self.stack_context.__exit__(None, None, None)

    def get_app(self):
        return app()

    def test_no_tracer(self):
        self.http_client.fetch(self.get_url('/'), self.stop)

        response = self.wait()
        self.assertEqual(response.code, 200)

        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].span_kind, span_module.SpanKind.CLIENT)
        self.assertEqual(spans[0].name, '[tornado.http_client]GET')
        self.assertEqual(spans[0].attributes[HTTP_STATUS_CODE], '200')
        assert spans[0].attributes[HTTP_URL].startswith('http://localhost')

    def test_simple(self):
        self.http_client.fetch(self.get_url('/'), self.stop)

        response = self.wait()
        self.assertEqual(response.code, 200)

        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].span_kind, span_module.SpanKind.CLIENT)
        self.assertEqual(spans[0].name, '[tornado.http_client]GET')
        self.assertEqual(spans[0].attributes[HTTP_STATUS_CODE], '200')
        assert spans[0].attributes[HTTP_URL].startswith('http://localhost')

    def test_explicit_parameters(self):
        self.http_client.fetch(self.get_url('/error'),
                               self.stop,
                               raise_error=False,
                               method='POST',
                               body='')
        response = self.wait()
        self.assertEqual(response.code, 500)

        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].span_kind, span_module.SpanKind.CLIENT)
        self.assertEqual(spans[0].name, '[tornado.http_client]POST')
        self.assertEqual(spans[0].attributes[HTTP_STATUS_CODE], '500')
        assert spans[0].attributes[HTTP_URL].startswith('http://localhost')

    def test_request_obj(self):
        self.http_client.fetch(HTTPRequest(self.get_url('/')), self.stop)

        response = self.wait()

        self.assertEqual(response.code, 200)

        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].span_kind, span_module.SpanKind.CLIENT)
        self.assertEqual(spans[0].name, '[tornado.http_client]GET')
        self.assertEqual(spans[0].attributes[HTTP_STATUS_CODE], '200')
        assert spans[0].attributes[HTTP_URL].startswith('http://localhost')

    def test_server_error(self):
        self.http_client.fetch(self.get_url('/error'), self.stop)

        response = self.wait()
        self.assertEqual(response.code, 500)

        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)

    def test_server_not_found(self):
        self.http_client.fetch(self.get_url('/doesnotexist'), self.stop)

        response = self.wait()
        self.assertEqual(response.code, 404)

        spans = self.exporter.spans[0]
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].span_kind, span_module.SpanKind.CLIENT)
        self.assertEqual(spans[0].attributes[HTTP_STATUS_CODE], '404')
        assert spans[0].attributes[HTTP_URL].startswith('http://localhost')
