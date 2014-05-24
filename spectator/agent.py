"""Agent program with web front-end."""


import tornado
import tornado.httpserver
import tornado.web
import tornado.websocket
import zmq
import zmq.eventloop.zmqstream


# PyLint complains about stuff required by PyZMQ and Tornado.
#
# pylint: disable=arguments-differ
# pylint: disable=attribute-defined-outside-init
# pylint: disable=no-member
# pylint: disable=too-many-public-methods


class Agent(object):
    """Resident program that monitors process resources.

    Each agent program has one instance of this class, which responds to
    requests from and publishes updates to client sessions.

    Client sessions connect to the agent's ZMQ `REP` and `PUB` socket pair to
    issue commands and receive updates."""

    def __init__(self, io_loop, context, control, updates):
        self.io_loop = io_loop
        self.context = context
        print 'Agent: binding REP socket to %r.' % control
        self.control = context.socket(zmq.REP)
        self.control.bind(control)
        self.control = zmq.eventloop.zmqstream.ZMQStream(self.control,
                                                         self.io_loop)
        self.control.on_recv(self.on_command)
        print 'Agent: binding PUB socket to %r.' % updates
        self.updates = context.socket(zmq.PUB)
        self.updates.bind(updates)
        self.updates = zmq.eventloop.zmqstream.ZMQStream(self.updates,
                                                         self.io_loop)

    def shutdown(self):
        """Stop accepting commands and stop publishing updates."""
        print 'Agent: closing ZMQ sockets.'
        self.updates.close()
        self.updates = None
        self.control.close()
        self.control = None
        print 'Agent: ZMQ sockets closed.'

    def on_command(self, message):
        """Process incoming command from the client (from ZMQ `REP` socket)."""
        print 'Agent: got message "%s".' % message
        self.control.send_multipart(['OK'])
        self.updates.send_multipart(message)


class Session(tornado.websocket.WebSocketHandler):
    """Bridge between a WebSocket connection and the agent.

    This session uses a ZMQ `DEALER` and `SUB` socket pair to communicate with
    the agent on one end, and a WebSocket to communicate with the client on the
    other end.

    There is one instance of this class per WebSocket connection."""

    @staticmethod
    def zmq_connect(context, protocol, url):
        """One-line way to create & connect a ZMQ socket."""
        socket = context.socket(protocol)
        socket.connect(url)
        return socket

    def initialize(self, context, control, updates):
        """Store context passed-in by the application (during start-up)."""
        self.context = context
        self.control = control
        self.updates = updates

    def open(self):
        """."""
        print 'Session: connected.'
        self.set_nodelay(True)
        # Connect to the all seeing eye to check for updates.
        #
        # NOTE: nothing will be received until we subscribe to at least one
        #       channel.  Wait for client to send messages that register for
        #       subscriptions.
        print 'Connecting DEALER socket to %r.' % self.control
        self.control = self.zmq_connect(self.context, zmq.DEALER, self.control)
        self.control = zmq.eventloop.zmqstream.ZMQStream(self.control,
                                                         self.stream.io_loop)
        self.control.on_recv(self.on_reply)
        print 'Connecting SUB socket to %r.' % self.updates
        self.updates = self.zmq_connect(self.context, zmq.SUB, self.updates)
        self.updates.setsockopt(zmq.SUBSCRIBE, '')
        self.updates = zmq.eventloop.zmqstream.ZMQStream(self.updates,
                                                         self.stream.io_loop)
        self.updates.on_recv(self.on_update)
        print 'Session: waiting for messages.'

    def select_subprotocol(self, protocols):
        """Determine if we support the sub-protocol rquested by the client."""
        print 'Session: selecting protocol'
        for protocol in protocols:
            if protocol.lower() == 'spectator':
                return protocol
        return None

    def on_message(self, message):
        """Forward incoming comment to the agent (from WebSocket)."""
        print 'Session: got message "%s"' % message
        if isinstance(message, unicode):
            message = message.encode('utf-8')
        self.control.send_multipart(['', message])

    def on_reply(self, message):
        """Forward outoing reply to the client (from ZMQ `DEALER` socket)."""
        for part in message[1:]:
            self.write_message(part)

    def on_update(self, message):
        """Forward outgoing update to the client (from ZMQ `SUB` socket)."""
        print 'Session: got update %r.' % message
        for part in message:
            self.write_message(part)

    def on_close(self):
        """Free all resources (the WebSocket connection was just closed)."""
        print 'Session: connection lost.'
        self.control.close()
        self.control = None
        self.updates.close()
        self.updates = None
        print 'Session: ZMQ sockets closed.'


def main(arguments):  # pylint: disable=unused-argument
    """Entry point for the spectator agent program."""
    context = zmq.Context()
    agent = Agent(context, 'inproc://control', 'inproc://updates')
    application = tornado.web.Application([
        (r'/', Session, {'context': context,
                         'control': 'inproc://control',
                         'updates': 'inproc://updates'}),
        (r'/', tornado.web.StaticFileHandler, {'path': './static/'})
    ])
    http_server = tornado.httpserver.HTTPServer(application)
    http_server.listen(9000)
    tornado.ioloop.IOLoop.instance().start()
    agent.shutdown()


if __name__ == '__main__':  # pragma: nocover
    import sys
    main(sys.argv[:])
