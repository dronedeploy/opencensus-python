import threading

from tornado import stack_context

# Modified from https://github.com/opentracing/opentracing-python/blob/master/opentracing/scope_managers/tornado.py


class ThreadSafeStackContext(stack_context.StackContext):
    """
    Thread safe version of Tornado's StackContext (up to 4.3)
    Copy of implementation by caspersj@, until tornado-extras is open-sourced.
    Tornado's StackContext works as follows:
    - When entering a context, create an instance of StackContext and
      add add this instance to the current "context stack"
    - If execution transfers to another thread (using the wraps helper
      method),  copy the current "context stack" and apply that in the new
      thread when execution starts
    - A context stack can be entered/exited by traversing the stack and
      calling enter/exit on all elements. This is how the `wraps` helper
      method enters/exits in new threads.
    - StackContext has an internal pointer to a context factory (i.e.
      RequestContext), and an internal stack of applied contexts (instances
      of RequestContext) for each instance of StackContext. RequestContext
      instances are entered/exited from the stack as the StackContext
      is entered/exited
    - However, the enter/exit logic and maintenance of this stack of
      RequestContext instances is not thread safe.
    ```
    def __init__(self, context_factory):
        self.context_factory = context_factory
        self.contexts = []
        self.active = True
    def enter(self):
        context = self.context_factory()
        self.contexts.append(context)
        context.__enter__()
    def exit(self, type, value, traceback):
        context = self.contexts.pop()
        context.__exit__(type, value, traceback)
    ```
    Unexpected semantics of Tornado's default StackContext implementation:
    - There exist a race on `self.contexts`, where thread A enters a
      context, thread B enters a context, and thread A exits its context.
      In this case, the exit by thread A pops the instance created by
      thread B and calls exit on this instance.
    - There exists a race between `enter` and `exit` where thread A
      executes the two first statements of enter (create instance and
      add to contexts) and thread B executes exit, calling exit on an
      instance that has been initialized but not yet exited (and
      subsequently this instance will then be entered).
    The ThreadSafeStackContext changes the internal contexts stack to be
    thread local, fixing both of the above issues.
    """

    def __init__(self, *args, **kwargs):
        class LocalContexts(threading.local):
            def __init__(self):
                super(LocalContexts, self).__init__()
                self._contexts = []

            def append(self, item):
                self._contexts.append(item)

            def pop(self):
                return self._contexts.pop()

        super(ThreadSafeStackContext, self).__init__(*args, **kwargs)

        if hasattr(self, 'contexts'):
            # only patch if context exists
            self.contexts = LocalContexts()


class _TracerRequestContext(object):
    __slots__ = ('attrs', 'current_span', 'tracer',)


class _TracerRequestContextManager(object):
    _state = threading.local()
    _state.context = None

    @classmethod
    def current_context(cls):
        return getattr(cls._state, 'context', None)

    def __init__(self, context):
        self._context = context

    def __enter__(self):
        self._prev_context = self.__class__.current_context()
        self.__class__._state.context = self._context
        return self._context

    def __exit__(self, *_):
        self.__class__._state.context = self._prev_context
        self._prev_context = None
        return False


def tracer_stack_context():
    context = _TracerRequestContext()
    return ThreadSafeStackContext(lambda: _TracerRequestContextManager(context))
