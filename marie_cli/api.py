from typing import TYPE_CHECKING

from docarray.documents.legacy import LegacyDocument

from marie.parsers.helper import _update_gateway_args
from marie.utils.pydantic import patch_pydantic_schema_2x

if TYPE_CHECKING:
    from argparse import Namespace


def deployment(args: "Namespace"):
    """
    Start a Deployment

    :param args: arguments coming from the CLI.
    """
    from marie.orchestrate.deployments import Deployment

    if args.uses:
        dep = Deployment.load_config(args.uses)
        with dep:
            dep.block()
    else:
        raise ValueError("starting a Deployment from CLI requires a valid `--uses`")


def pod(args: "Namespace"):
    """
    Start a Pod

    :param args: arguments coming from the CLI.
    """
    from marie.orchestrate.pods.factory import PodFactory

    try:
        with PodFactory.build_pod(args) as p:
            p.join()
    except KeyboardInterrupt:
        pass


def executor_native(args: "Namespace"):
    """
    Starts an Executor in a WorkerRuntime

    :param args: arguments coming from the CLI.
    """
    from marie.serve.runtimes.asyncio import AsyncNewLoopRuntime

    if args.runtime_cls == "WorkerRuntime":
        from marie.serve.runtimes.worker.request_handling import WorkerRequestHandler

        req_handler_cls = WorkerRequestHandler
    elif args.runtime_cls == "HeadRuntime":
        from marie.serve.runtimes.head.request_handling import HeaderRequestHandler

        req_handler_cls = HeaderRequestHandler
    else:
        raise RuntimeError(
            f" runtime_cls {args.runtime_cls} is not supported with `--native` argument. `WorkerRuntime` is supported"
        )

    with AsyncNewLoopRuntime(args, req_handler_cls=req_handler_cls) as rt:
        name = (
            rt.server._request_handler._executor.metas.name
            if hasattr(rt.server, "_request_handler")
            and hasattr(rt.server._request_handler, "_executor")
            else args.runtime_cls
        )
        rt.logger.info(f"Executor {name} started")
        rt.run_forever()


def executor(args: "Namespace"):
    """
    Starts an Executor in any Runtime

    :param args: arguments coming from the CLI.

    :returns: return the same as `pod` or `worker_runtime`
    """
    args.host = args.host[0]
    args.port_monitoring = args.port_monitoring[0]

    if args.native:
        return executor_native(args)
    else:
        return pod(args)


def gateway(args: "Namespace"):
    """
    Start a Gateway Deployment

    :param args: arguments coming from the CLI.
    """
    from marie.serve.runtimes.asyncio import AsyncNewLoopRuntime
    from marie.serve.runtimes.gateway.request_handling import GatewayRequestHandler

    args.port_monitoring = args.port_monitoring[0]
    _update_gateway_args(args)

    with AsyncNewLoopRuntime(args, req_handler_cls=GatewayRequestHandler) as runtime:
        runtime.logger.info(f"Gateway started")
        runtime.run_forever()


def ping(args: "Namespace"):
    """
    Check the connectivity of a Pod

    :param args: arguments coming from the CLI.
    """
    from marie.checker import NetworkChecker

    NetworkChecker(args)


def dryrun(args: "Namespace"):
    """
    Check the health of a Flow

    :param args: arguments coming from the CLI.
    """
    from marie.checker import dry_run_checker

    dry_run_checker(args)


def client(args: "Namespace"):
    """
    Start a client connects to the gateway

    :param args: arguments coming from the CLI.
    """
    from marie.clients import Client

    Client(args)


def export(args: "Namespace"):
    """
    Export the API

    :param args: arguments coming from the CLI.
    """
    from marie import exporter

    getattr(exporter, f'export_{args.export.replace("-", "_")}')(args)


def flow(args: "Namespace"):
    """
    Start a Flow from a YAML file or a docker image

    :param args: arguments coming from the CLI.
    """
    from marie import Flow

    if args.uses:
        f = Flow.load_config(args.uses)
        with f:
            f.block()
    else:
        raise ValueError("starting a Flow from CLI requires a valid `--uses`")


def hub(args: "Namespace"):
    """
    Start a hub builder for push, pull
    :param args: arguments coming from the CLI.
    """
    from hubble.executor.hubio import HubIO

    getattr(HubIO(args), args.hub_cli)()


def new(args: "Namespace"):
    """
    Create a new jina project
    :param args:  arguments coming from the CLI.
    """
    import os
    import shutil

    from marie.constants import __resources_path__

    if args.type == "deployment":
        shutil.copytree(
            os.path.join(__resources_path__, "project-template", "deployment"),
            os.path.abspath(args.name),
        )
    else:
        shutil.copytree(
            os.path.join(__resources_path__, "project-template", "flow"),
            os.path.abspath(args.name),
        )


def help(args: "Namespace"):
    """
    Lookup the usage of certain argument in Marie API.

    :param args: arguments coming from the CLI.
    """
    from marie_cli.lookup import lookup_and_print

    lookup_and_print(args.query.lower())


def auth(args: "Namespace"):
    """
    Authenticate a user
    :param args: arguments coming from the CLI.
    """
    from hubble import api

    getattr(api, args.auth_cli.replace("-", "_"))(args)


def cloud(args: "Namespace"):
    """
    Use jcloud (Jina Cloud) commands
    :param args: arguments coming from the CLI.
    """
    raise NotImplementedError


def server(args: "Namespace"):
    """
    Marie server CLI
    :param args: arguments coming from the CLI.
    """
    import os

    from marie.constants import __config_dir__
    from marie_server import __main__ as srv

    # marie server watch --etcd-host 127.0.0.1
    # if args.ctl_cli == "watch":
    #     watch_sever_deployments(args)
    #     return

    if args.uses:
        _input = args.uses
    else:
        _input = os.path.join(__config_dir__, "service", "marie.yml")

    srv.main(yml_config=_input, env=args.env, env_file=args.env_file)
