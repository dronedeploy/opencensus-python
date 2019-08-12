import pymongo
import pytest

from opencensus.trace import config_integration
from opencensus.trace import tracer as tracer_module
from opencensus.trace.exporters.capturing_exporter import CapturingExporter
from opencensus.trace.ext.pymongo.trace import _normalize_filter
from opencensus.trace.propagation.google_cloud_format import GoogleCloudFormatPropagator
from opencensus.trace.samplers import AlwaysOnSampler

config_integration.trace_integrations(['pymongo'])


@pytest.fixture(autouse=True)
def exporter():
    exporter = CapturingExporter()
    tracer_module.Tracer(
        sampler=AlwaysOnSampler(),
        exporter=exporter,
        propagator=GoogleCloudFormatPropagator()
    )
    return exporter


@pytest.fixture(autouse=True)
def client():
    return pymongo.MongoClient(port=27017)


def test_normalize_filter():
    cases = [
        (None, {}),
        (
            {'team': 'leafs'},
            {'team': '?'},
        ),
        (
            {'age': {'$gt': 20}},
            {'age': {'$gt': '?'}},
        ),
        (
            {'age': {'$gt': 20}},
            {'age': {'$gt': '?'}},
        ),
        (
            {'_id': {'$in': [1, 2, 3]}},
            {'_id': {'$in': '?'}},
        ),
        (
            {'_id': {'$nin': [1, 2, 3]}},
            {'_id': {'$nin': '?'}},
        ),

        (
            20,
            {},
        ),
        (
            {
                'status': 'A',
                '$or': [{'age': {'$lt': 30}}, {'type': 1}],
            },
            {
                'status': '?',
                '$or': [{'age': {'$lt': '?'}}, {'type': '?'}],
            },
        ),
    ]
    for i, expected in cases:
        out = _normalize_filter(i)
        assert expected == out


def test_update(client, exporter):
    # ensure we trace deletes
    db = client['testdb']
    db.drop_collection('songs')
    input_songs = [
        {'name': 'Powderfinger', 'artist': 'Neil'},
        {'name': 'Harvest', 'artist': 'Neil'},
        {'name': 'Suzanne', 'artist': 'Leonard'},
        {'name': 'Partisan', 'artist': 'Leonard'},
    ]
    db.songs.insert_many(input_songs)

    result = db.songs.update_many(
        {'artist': 'Neil'},
        {'$set': {'artist': 'Shakey'}},
    )

    eq_(result.matched_count, 2)
    eq_(result.modified_count, 2)

    # ensure all is traced.
    spans = exporter.spans
    queries = []
    for span_list in spans:
        for span in span_list:
            # ensure all the of the common attributesdata is set
            eq_(span.attributes.get('pymongo.collection'), 'songs')
            eq_(span.attributes.get('pymongo.db'), 'testdb')
            queries.append(span.attributes.get('pymongo.query'))

    expected_resources = ['drop songs', 'insert songs', 'update songs {"artist": "?"}']
    assert expected_resources == queries


def test_delete(client, exporter):
    # ensure we trace deletes
    db = client['testdb']
    collection_name = 'here.are.songs'
    db.drop_collection(collection_name)
    input_songs = [
        {'name': 'Powderfinger', 'artist': 'Neil'},
        {'name': 'Harvest', 'artist': 'Neil'},
        {'name': 'Suzanne', 'artist': 'Leonard'},
        {'name': 'Partisan', 'artist': 'Leonard'},
    ]

    songs = db[collection_name]
    songs.insert_many(input_songs)

    # test delete one
    af = {'artist': 'Neil'}
    eq_(songs.count(af), 2)
    songs.delete_one(af)
    eq_(songs.count(af), 1)

    # test delete many
    af = {'artist': 'Leonard'}
    eq_(songs.count(af), 2)
    songs.delete_many(af)
    eq_(songs.count(af), 0)

    # ensure all is traced.
    spans = exporter.spans
    queries = []
    for span_list in spans:
        for span in span_list:
            # ensure all the of the common attributesdata is set
            eq_(span.attributes.get('pymongo.collection'), collection_name)
            eq_(span.attributes.get('pymongo.db'), 'testdb')
            queries.append(span.attributes.get('pymongo.query'))

    expected_resources = [
        'drop here.are.songs',
        'insert here.are.songs',
        'count here.are.songs',
        'delete here.are.songs {"artist": "?"}',
        'count here.are.songs',
        'count here.are.songs',
        'delete here.are.songs {"artist": "?"}',
        'count here.are.songs',
    ]

    assert expected_resources == queries


def test_insert_find(client, exporter):
    db = client.testdb
    db.drop_collection('teams')
    teams = [
        {
            'name': 'Toronto Maple Leafs',
            'established': 1917,
        },
        {
            'name': 'Montreal Canadiens',
            'established': 1910,
        },
        {
            'name': 'New York Rangers',
            'established': 1926,
        }
    ]

    # create some data (exercising both ways of inserting)

    db.teams.insert_one(teams[0])
    db.teams.insert_many(teams[1:])

    # wildcard query (using the [] syntax)
    cursor = db['teams'].find()
    count = 0
    for row in cursor:
        count += 1
    eq_(count, len(teams))

    # scoped query (using the getattr syntax)
    q = {'name': 'Toronto Maple Leafs'}
    queried = list(db.teams.find(q))
    eq_(len(queried), 1)
    eq_(queried[0]['name'], 'Toronto Maple Leafs')
    eq_(queried[0]['established'], 1917)

    spans = exporter.spans
    queries = []
    for span_list in spans:
        for span in span_list:
            # ensure all the of the common attributesdata is set
            eq_(span.attributes.get('pymongo.collection'), 'teams')
            eq_(span.attributes.get('pymongo.db'), 'testdb')
            queries.append(span.attributes.get('pymongo.query'))

    expected_resources = [
        'drop teams',
        'insert teams',
        'insert teams',
    ]

    # query names should be used in >3.1
    name = 'find' if pymongo.version_tuple >= (3, 1, 0) else 'query'

    expected_resources.extend([
        '{} teams'.format(name),
        '{} teams {{"name": "?"}}'.format(name),
    ])

    eq_(expected_resources, queries)


def eq_(first, second):
    assert first == second
