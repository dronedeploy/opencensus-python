import pytest
import tornado
from concurrent import futures
from tornado import web
from tornado.concurrent import run_on_executor

from opencensus.trace import execution_context as ec, config_integration
from opencensus.trace.exporters.capturing_exporter import CapturingExporter
from opencensus.trace.ext.tornado.trace import DEFAULT_TORNADO_TRACER_CONFIG, BLACKLIST_PATHS, EXPORTER_KEY, CONFIG_KEY


config_integration.trace_integrations(['tornado'])


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.write('{}')


class BlacklistHandler(tornado.web.RequestHandler):
    def get(self):
        span = ec.get_current_span()
        assert span is None


class ErrorHandler(tornado.web.RequestHandler):
    def get(self):
        raise ValueError()


class ScopeHandler(tornado.web.RequestHandler):

    @tornado.gen.coroutine
    def do_something(self, span):
        tracer = ec.get_opencensus_tracer()
        with tracer.start_span('child') as child_span:
            assert span.span_id == child_span.parent_span.span_id
            yield tornado.gen.sleep(0.0)

    @tornado.gen.coroutine
    def get(self):
        span = ec.get_current_span()
        assert span is not None
        yield self.do_something(span)
        assert ec.get_current_span() is span
        self.write('{}')


class ThreadPoolHandler(tornado.web.RequestHandler):
    executor = futures.ThreadPoolExecutor(max_workers=1)

    @run_on_executor
    def do_something(self, span):
        tracer = ec.get_opencensus_tracer()
        with tracer.start_span('child') as child_span:
            assert span.span_id == child_span.parent_span.span_id
            yield tornado.gen.sleep(0.0)

    @tornado.gen.coroutine
    def get(self):
        span = ec.get_current_span()
        assert span is not None
        yield self.do_something(span)
        assert ec.get_current_span() is span
        self.write('{}')


@pytest.fixture
def app(exporter):
    trace_settings = DEFAULT_TORNADO_TRACER_CONFIG.copy()
    trace_settings[BLACKLIST_PATHS] = ['blacklisted']
    trace_settings[EXPORTER_KEY] = exporter

    settings = {
        CONFIG_KEY: trace_settings
    }
    app = tornado.web.Application(
        [
            ('/', MainHandler),
            ('/error', ErrorHandler),
            ('/coroutine', ScopeHandler),
            ('/threadpool', ThreadPoolHandler),
            ('/blacklisted', MainHandler),
        ],
        **settings
    )
    return app


@pytest.fixture(autouse=True)
def exporter():
    exporter = CapturingExporter()
    return exporter


@pytest.mark.gen_test
def test_hello_world(http_client, base_url, exporter):
    response = yield http_client.fetch(base_url)
    assert response.code == 200
    assert 1 == len(exporter.spans)


@pytest.mark.gen_test
def test_coroutine(http_client, base_url, exporter):
    response = yield http_client.fetch(base_url + '/coroutine')
    assert response.code == 200
    assert 2 == len(exporter.spans)
    assert 'child' == exporter.spans[0][0].name
    assert exporter.spans[1][0].span_id == exporter.spans[0][0].parent_span_id


@pytest.mark.gen_test
def test_threadpool(http_client, base_url, exporter):
    response = yield http_client.fetch(base_url + '/threadpool')
    assert response.code == 200
    assert 1 == len(exporter.spans)


@pytest.mark.gen_test
def test_error(http_client, base_url, exporter):
    with pytest.raises(BaseException) as e:
        yield http_client.fetch(base_url + '/error')
    assert e.value.code == 500
    assert 1 == len(exporter.spans)


@pytest.mark.gen_test
def test_blacklist(http_client, base_url, exporter):
    response = yield http_client.fetch(base_url + '/blacklisted')
    assert response.code == 200
    assert 0 == len(exporter.spans)
