"""
app/errors.py
=============
Custom HTTP error handlers for SkillSwap.

Registers handlers for 400, 403, 404 and 500 that return
user-friendly HTML pages when Flask is running in production
mode, and plain JSON when the request expects JSON.
"""

from flask import render_template, jsonify, request


def register_error_handlers(app):
    """Attach all custom error handlers to *app*."""

    def _wants_json():
        best = request.accept_mimetypes.best_match(
            ['application/json', 'text/html']
        )
        return best == 'application/json'

    @app.errorhandler(400)
    def bad_request(e):
        if _wants_json():
            return jsonify(error=str(e), code=400), 400
        return render_template('errors/400.html', error=e), 400

    @app.errorhandler(403)
    def forbidden(e):
        if _wants_json():
            return jsonify(error='Forbidden', code=403), 403
        return render_template('errors/403.html', error=e), 403

    @app.errorhandler(404)
    def not_found(e):
        if _wants_json():
            return jsonify(error='Not found', code=404), 404
        return render_template('errors/404.html', error=e), 404

    @app.errorhandler(500)
    def server_error(e):
        if _wants_json():
            return jsonify(error='Internal server error', code=500), 500
        return render_template('errors/500.html', error=e), 500
