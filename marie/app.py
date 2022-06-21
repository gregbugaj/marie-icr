from __future__ import absolute_import

import sys
import os
import traceback

import torch

import conf
from api import api
from flask import Flask

from arg_parser import ArgParser

import marie.api.IcrAPIRoutes as IcrAPIRoutes
import marie.api.WorkflowRoutes as WorkflowRoutes
from marie.api.icr_router import ICRRouter
from marie.api.route_handler import RouteHandler
from marie.api.sample_route import SampleRouter

from marie.common.volume_handler import VolumeHandler
from marie.logging.logger import MarieLogger
from marie.logging.predefined import default_logger
from marie.utils.network import find_open_port
from marie.version import __version__
from marie.common.file_io import PathManager
from marie import __cache_dir__

# from marie.logger import setup_logger
from marie.utils.utils import ensure_exists, FileSystem

# from api.IcrAPIRoutes import IcrAPIRoutes # TypeError: 'module' object is not callable
logger = default_logger


def create_app():
    logger.info(f"Starting app in {conf.APP_ENV} environment")
    ensure_exists(f"/tmp/marie")
    # Register VFS handlers
    base_dir = FileSystem.get_share_directory()
    PathManager.register_handler(VolumeHandler(volume_base_dir=base_dir))
    # PathManager.register_handler(VolumeHandler(volume_base_dir="/home/gbugaj/datasets/medprov/"))
    # PathManager.register_handler(VolumeHandler(volume_base_dir="/opt/shares/medrxprovdata/"))
    # PathManager.register_handler(VolumeHandler(volume_base_dir="/opt/prodshare/"))

    app = Flask(__name__)
    app.config.from_object(conf)
    app.config["APPLICATION_ROOT"] = "/api"

    api.init_app(app)

    @app.route("/")
    def index():
        return {"version": __version__}

    with app.app_context():
        # app.register_blueprint(IcrAPIRoutes.blueprint)
        # app.register_blueprint(WorkflowRoutes.blueprint)
        # RouteHandler.register_route(SampleRouter(app))
        RouteHandler.register_route(ICRRouter(app))

    return app


if __name__ == "__main__":
    # import sys
    # for p in sys.path:
    #     print(p)

    # export PYTHONPATH = "$PWD"
    pypath = os.environ["PYTHONPATH"]
    # os.environ["MARIE_DEFAULT_SHARE_PATH"] = "/opt/shares/medrxprovdata"

    args = ArgParser.server_parser()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Initializing 🦊-Marie : %s", __version__)
    logger.info("[PID]%d [UID]%d", os.getpid(), os.getuid())
    logger.info("Python runtime: %s", sys.version.replace("\n", ""))
    logger.info("Environment : %s", conf.APP_ENV)
    logger.info("Torch version : %s", torch.__version__)
    logger.info("Using device: %s", device)
    # Additional Info when using cuda
    if device.type == "cuda":
        logger.info("Device : %s", torch.cuda.get_device_name(0))
        logger.info(
            "GPU Memory Allocated: %d GB",
            round(torch.cuda.memory_allocated(0) / 1024 ** 3, 1),
        )
        logger.info(
            "GPU Memory Cached: %d GB",
            round(torch.cuda.memory_reserved(0) / 1024 ** 3, 1),
        )

    # Setting use_reloader to false prevents application from initializing twice
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["FLASK_DEBUG"] = "1"

    # by default cache is located in '~/.cache' here we will map it under the runtime cache directory
    os.environ["TORCH_HOME"] = str(__cache_dir__)

    # os.environ["MARIE_PORT"] = "-1"

    logger.info(f"Environment variables")
    for k, v in os.environ.items():
        logger.info(f"env : {k}={v}")

    server_port = os.getenv("MARIE_PORT", 5000)
    if server_port == "-1":
        server_port = find_open_port()
    else:
        server_port = int(server_port)

    with open("port.dat", "w", encoding="utf-8") as fsrc:
        fsrc.write(f"{server_port}")
        print(f"server_port = {server_port}")

    service = create_app()
    service.run(host="0.0.0.0", port=server_port, debug=False, use_reloader=False)
