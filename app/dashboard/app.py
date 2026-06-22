"""Standalone Flask app factory for the local-only Conduit dashboard."""

from __future__ import annotations

from flask import Flask, abort, jsonify, request

from .blueprint import dashboard_blueprint

_LOCAL_ADDRESSES = {"127.0.0.1", "::1"}


def create_dashboard_app(config_object: str = "app.settings") -> Flask:
    """Create the dashboard Flask app without registering proxy routes.

    The dashboard is unauthenticated by design and binds to loopback only. This
    app-level guard rejects non-local remotes if it is ever mis-bound.
    """
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.register_blueprint(dashboard_blueprint)

    @app.before_request
    def reject_non_local() -> None:
        if (request.remote_addr or "").lower() not in _LOCAL_ADDRESSES:
            abort(403)

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "service": "dashboard"})

    return app
