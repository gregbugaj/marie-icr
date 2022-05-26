from __future__ import absolute_import

import os
import sys

import torch

import conf
import marie
import marie.helper

from marie.logger import setup_logger
from marie.logging.logger import MarieLogger
from marie.parsers import set_gateway_parser
from marie.serve.runtimes.gateway.http import HTTPGatewayRuntime
from marie.version import __version__

# logger = setup_logger(__file__)
logger = MarieLogger('')

def main():
    args = set_gateway_parser().parse_args(["--port", "5000", "--title", "Foxy Marie"])

    def extend_rest_function(app):
        @app.get('/hello', tags=['My Extended APIs'])
        async def foo():
            """Testing extended REST function"""
            return {'msg': 'hello world'}

        return app

    marie.helper.extend_rest_interface = extend_rest_function
    logger.info(args)
    gateway = HTTPGatewayRuntime(args)
    gateway.run_forever()


if __name__ == "__main__":
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Starting 🦊-Marie Service: %s", __version__)
    logger.info("[PID]%d [UID]%d", os.getpid(), os.getuid())
    logger.info("Python runtime: %s", sys.version.replace("\n", ""))
    logger.info("Environment : %s", conf.APP_ENV)
    logger.info("Torch version : %s", torch.__version__)
    logger.info("Using device: %s", device)
    # Additional Info when using cuda
    if device.type == "cuda":
        logger.info("Device : %s", torch.cuda.get_device_name(0))
        logger.info("GPU Memory Allocated: %d GB", round(torch.cuda.memory_allocated(0) / 1024**3, 1))
        logger.info("GPU Memory Cached: %d GB", round(torch.cuda.memory_reserved(0) / 1024**3, 1))

    if __name__ == "__main__":
        main()

#         http://localhost:5000/redoc

