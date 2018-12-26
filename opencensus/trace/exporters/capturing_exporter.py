from opencensus.trace.exporters.base import Exporter


class CapturingExporter(Exporter):

    def __init__(self):
        super(CapturingExporter, self).__init__()
        self._spans = []

    @property
    def spans(self):
        return self._spans

    def emit(self, span_datas):
        pass

    def export(self, span_datas):
        self._spans.append(span_datas)
