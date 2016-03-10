# -*-  coding: utf-8 -*-
"""
tornado websocket proxy for WF worker daemons
"""
# Copyright (C) 2015 ZetaOps Inc.
#
# This file is licensed under the GNU General Public License v3
# (GPLv3).  See LICENSE.txt for details.
import json
import traceback

from tornado.escape import json_decode, json_encode
from tornado.httpclient import HTTPError

from pyoko.lib.utils import get_object_from_path
from zengine.engine import ZEngine, Current
from zengine.lib.cache import Session
from zengine.queue_manager import QueueManager
from uuid import uuid4
from zengine.config import settings
from tornado import websocket, web, ioloop
from zengine.log import log

COOKIE_NAME = 'zopsess'
CLIENT_SOCKETS = {}


class SocketHandler(websocket.WebSocketHandler):
    """
    websocket handler
    """

    def check_origin(self, origin):
        """
        Prevents CORS attacks.

        Args:
            origin: HTTP "Origin" header. URL of initiator of the request.

        Returns:
            True if origin is legit, otherwise False
        """
        # FIXME: implement CORS checking
        return True

    def _get_sess_id(self):
        # return self.sess_id;
        sess_id = self.get_cookie(COOKIE_NAME)
        return sess_id

    def open(self):
        """
        Called on new websocket connection.
        """
        sess_id = self._get_sess_id()
        if sess_id:
            self.application.pc.register_websocket(self._get_sess_id(), self)
        else:
            self.write_message(json.dumps({"error": "Please login", "code": 401}))

    def on_message(self, message):
        """
        called on new websocket message,
        """
        print("WS MESSAGE: %s" % message)
        self.application.pc.redirect_incoming_message(self._get_sess_id(), message)

    def on_close(self):
        """
        remove connection from pool on connection close.
        """
        print("Websocket closed")
        self.application.pc.unregister_websocket(self._get_sess_id())


class LoginHandler(web.RequestHandler):
    """
    login handler class
    """


    @web.asynchronous
    def get(self):
        self.post()

    @web.asynchronous
    def post(self):
        """
        login handler
        """
        try:
            wf_engine = ZEngine()
            self.set_header('Access-Control-Allow-Origin', self.request.headers.get('Origin'))
            self.set_header('Access-Control-Allow-Credentials', 'true')
            self.set_header('Content-Type', 'application/json')
            sess_id = uuid4().hex
            session = Session(sess_id)
            self.set_cookie(COOKIE_NAME, sess_id)  # , domain='127.0.0.1'
            input_data = json_decode(self.request.body) if self.request.body else {}
            wf_engine.start_engine(session=session, input=input_data, workflow_name='login')
            wf_engine.run()
            # print("Set session cookie: %s" % sess_id)
            output = json.dumps(wf_engine.current.output.copy())
            # print(output)
            # self.write(output)
            # self.write("[{}]")
        except HTTPError as e:
            output = {'error': e.message, "code": e.code}
            self.set_status(int(e.code))
        except:
            if settings.DEBUG:
                self.set_status(500)
                output = json.dumps({'error': traceback.format_exc()})
                log.exception("500 ERROR")
            else:
                log.exception("500 ERROR")
                output = {'error': settings.ERROR_MESSAGE_500, "code": 500}
        self.write(output)
        self.finish()
        self.flush()


def tornado_view_connector(view_path):
    """
    A factory method for non-workflow views.

    Both Tornado requires an object that
    implements get and post methods for url mappings.
    This method returns a handler object that calls the given
    view class / function.

    Prevention of unauthenticated access and re-raising of
    internal server errors also done at this stage.

    Args:
        view_path: Python path of the view class/function.
    """

    view = get_object_from_path(view_path)

    # noinspection PyMissingOrEmptyDocstring
    class Caller(web.RequestHandler):
        def get(self):
            """
            GET method http handler
            """
            self.post()

        def post(self):
            """
                POST method http handler
            """
            try:
                sess_id = self.get_cookie(COOKIE_NAME)
                session = Session(sess_id)
                self.set_header('Access-Control-Allow-Origin', self.request.headers.get('Origin'))
                self.set_header('Access-Control-Allow-Credentials', 'true')
                self.set_header('Content-Type', 'application/json')
                input_data = json_decode(self.request.body) if self.request.body else {}
                current = Current(session=session, input=input_data)
                if not (current.is_auth or view_path in settings.ANONYMOUS_WORKFLOWS):
                    raise HTTPError(401)
                view(current)
                output = json.dumps(current.output.copy())
            except HTTPError as e:
                output = {'error': e.message, "code": e.code}
                self.set_status(int(e.code))
            except:
                if settings.DEBUG:
                    self.set_status(500)
                    output = json.dumps({'error': traceback.format_exc()})
                    log.exception("500 ERROR")
                else:
                    log.exception("500 ERROR")
                    output = {'error': settings.ERROR_MESSAGE_500, "code": 500}
            self.write(output)
            self.finish()
            self.flush()



    return Caller


URL_CONFS = [
    (r'/ws', SocketHandler),
    (r'/login', LoginHandler),
]

for url, view_path in settings.VIEW_URLS:
    URL_CONFS.append(("/" + url, tornado_view_connector(view_path)))

    app = web.Application(URL_CONFS, debug=settings.DEBUG)


def runserver(host="0.0.0.0", port=9001):
    """
    Run Tornado server
    """
    zioloop = ioloop.IOLoop.instance()

    # setup pika client
    pc = QueueManager(zioloop)
    app.pc = pc
    pc.connect()
    app.listen(port, host)
    zioloop.start()


if __name__ == '__main__':
    runserver()
