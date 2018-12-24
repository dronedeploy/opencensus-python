import pytest
import tornado
from concurrent import futures
from tornado import web
from tornado.concurrent import run_on_executor
from tornado.httpclient import HTTPClientError

from opencensus.trace import execution_context as ec, config_integration


config_integration.trace_integrations(['tornado'])


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.write('{}')


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
def app():
    settings = {}
    app = tornado.web.Application(
        [
            ('/', MainHandler),
            ('/error', ErrorHandler),
            ('/coroutine', ScopeHandler),
            ('/threadpool', ThreadPoolHandler),
        ],
        **settings
    )
    return app


@pytest.mark.gen_test
def test_hello_world(http_client, base_url):
    response = yield http_client.fetch(base_url)
    assert response.code == 200


@pytest.mark.gen_test
def test_coroutine(http_client, base_url):
    response = yield http_client.fetch(base_url + '/coroutine')
    assert response.code == 200


@pytest.mark.gen_test
def test_threadpool(http_client, base_url):
    response = yield http_client.fetch(base_url + '/threadpool')
    assert response.code == 200


@pytest.mark.gen_test
def test_error(http_client, base_url):
    with pytest.raises(HTTPClientError) as e:
        yield http_client.fetch(base_url + '/error')
    assert e.value.code == 500
