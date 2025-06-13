import os
from threading import Thread

import kombu.exceptions
from flask import Blueprint, Flask, current_app, request
from flask_httpauth import HTTPTokenAuth
from loguru import logger
from prometheus_client.exposition import choose_encoder
from waitress import serve

blueprint = Blueprint("celery_exporter", __name__)
auth = HTTPTokenAuth()

@auth.verify_token
def verify_user_token(token):
    return True if token == os.environ.get('BEARER_TOKEN') else False

@blueprint.route("/")
def index():
    return """
<!doctype html>
<html lang="en">
  <head>
    <!-- Required meta tags -->
    <meta charset="utf-8">
    <title>celery-exporter</title>
  </head>
  <body>
    <h1>Celery Exporter</h1>
    <p><a href="/metrics">Metrics</a></p>
  </body>
</html>
"""


@blueprint.route("/metrics")
@auth.login_required
def metrics():
    current_app.config["metrics_puller"]()
    encoder, content_type = choose_encoder(request.headers.get("accept"))
    output = encoder(current_app.config["registry"])
    return output, 200, {"Content-Type": content_type}


@blueprint.route("/health")
@auth.login_required
def health():
    conn = current_app.config["celery_connection"]
    uri = conn.as_uri()

    try:
        conn.ensure_connection(max_retries=3)
    except kombu.exceptions.OperationalError:
        logger.error("Failed to connect to broker='{}'", uri)
        return (f"Failed to connect to broker: '{uri}'", 500)
    except Exception:  # pylint: disable=broad-except
        logger.exception("Unrecognized error")
        return ("Unknown exception", 500)
    return f"Connected to the broker {conn.as_uri()}"


def start_http_server(registry, celery_connection, host, port, metrics_puller):
    app = Flask(__name__)
    app.config["registry"] = registry
    app.config["celery_connection"] = celery_connection
    app.config["metrics_puller"] = metrics_puller
    app.register_blueprint(blueprint)
    Thread(
        target=serve,
        args=(app,),
        kwargs=dict(host=host, port=port, _quiet=True),
        daemon=True,
    ).start()
    logger.info("Started celery-exporter at host='{}' on port='{}'", host, port)
