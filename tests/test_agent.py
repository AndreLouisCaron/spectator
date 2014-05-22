import logging
import os
import zmq
from functools import partial
from nose.tools import with_setup
from tornado.httpclient import AsyncHTTPClient
from tornado.httpserver import HTTPServer
from tornado.testing import AsyncTestCase
from tornado.web import Application, StaticFileHandler
from tornado.websocket import websocket_connect
from zmq.eventloop.ioloop import ZMQIOLoop

from spectator.agent import Agent, Session


__path__ = os.path.realpath(os.path.dirname(__file__))


class TestHybridSetup(AsyncTestCase):

    def get_new_ioloop(self):
        return ZMQIOLoop()

    def test_hybrid_setup(self):
        """The agent can serve static assets and bridge WebSockets to ZMQ."""
        # Prepare the async server.
        context = zmq.Context()
        agent = Agent(self.io_loop, context,
                      'inproc://control',
                      'inproc://updates')
        application = Application([
            (r'/', Session, {'context': context,
                             'control': 'inproc://control',
                             'updates': 'inproc://updates'}),
            (r'/assets/(.*)', StaticFileHandler, {'path': __path__})
        ])
        server = HTTPServer(application, io_loop=self.io_loop)
        server.listen(9000)
        # Perform a simple HTTP query for static file.
        client = AsyncHTTPClient()
        client.fetch('http://127.0.0.1:9000/assets/test_agent.html', self.stop)
        response = self.wait()  # note: no `.result()`?
        print response
        self.assertEqual(response.code, 200)
        # Async websocket client will verify behavior.
        websocket_connect('ws://127.0.0.1:9000',
                          io_loop=self.io_loop,
                          callback=self.stop)
        session = self.wait().result()
        # Send message and wait for reply.
        session.write_message('Hello, world!')
        session.read_message(self.stop)
        message = self.wait().result()
        self.assertEqual(message, 'Hello, world!')
        # Close connection and wait for confirmation.
        #
        # NOTE: without this, the session's `on_close()` handler will not be
        #       called, its ZMQ sockets will not be closed and `context.term()`
        #       will hang forever.
        session.close()
        session.read_message(self.stop)
        message = self.wait().result()
        self.assertEqual(message, None)
        # Close up shop.
        agent.shutdown()
        context.term()
