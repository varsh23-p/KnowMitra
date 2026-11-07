"""
run.py - Application entry point.

Uses socketio.run() instead of app.run() so that WebSocket
connections are handled correctly by Flask-SocketIO.

Run with: python run.py
"""
from app import create_app, socketio

app = create_app('development')

if __name__ == '__main__':
    # allow_unsafe_werkzeug=True is required when running SocketIO
    # with the Werkzeug dev server (fine for development).
    socketio.run(app, debug=True, port=5000, allow_unsafe_werkzeug=True)
