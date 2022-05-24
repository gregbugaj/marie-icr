import asyncio
import inspect
import json
import math
import os
import random
import re
import threading
import uuid
import warnings
from argparse import Namespace, ArgumentParser
from itertools import islice
from typing import Dict, TYPE_CHECKING, Optional, Tuple, Union, Callable, Sequence, Iterable, List, Any, Iterator, Set

from rich.console import Console


from marie import __windows__

# based on jina


def get_internal_ip():
    """
    Return the private IP address of the gateway for connecting from other machine in the same network.

    :return: Private IP address.
    """
    import socket

    ip = "127.0.0.1"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # doesn't even have to be reachable
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
    except Exception:
        pass
    return ip


def get_public_ip(timeout: float = 0.3):
    """
    Return the public IP address of the gateway for connecting from other machine in the public network.

    :param timeout: the seconds to wait until return None.

    :return: Public IP address.

    .. warn::
        Set `timeout` to a large number will block the Flow.

    """
    import urllib.request

    results = []

    def _get_ip(url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as fp:
                _ip = fp.read().decode().strip()
                results.append(_ip)

        except:
            pass  # intentionally ignored, public ip is not showed

    ip_server_list = [
        "https://api.ipify.org",
        "https://ident.me",
        "https://checkip.amazonaws.com/",
    ]

    threads = []

    for idx, ip in enumerate(ip_server_list):
        t = threading.Thread(target=_get_ip, args=(ip,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout)

    for r in results:
        if r:
            return r


def convert_tuple_to_list(d: Dict):
    """
    Convert all the tuple type values from a dict to list.

    :param d: Dict type of data.
    """
    for k, v in d.items():
        if isinstance(v, tuple):
            d[k] = list(v)
        elif isinstance(v, dict):
            convert_tuple_to_list(v)


def is_jupyter() -> bool:  # pragma: no cover
    """
    Check if we're running in a Jupyter notebook, using magic command `get_ipython` that only available in Jupyter.

    :return: True if run in a Jupyter notebook else False.
    """
    try:
        get_ipython  # noqa: F821
    except NameError:
        return False
    shell = get_ipython().__class__.__name__  # noqa: F821
    if shell == "ZMQInteractiveShell":
        return True  # Jupyter notebook or qtconsole
    elif shell == "Shell":
        return True  # Google colab
    elif shell == "TerminalInteractiveShell":
        return False  # Terminal running IPython
    else:
        return False  # Other type (?)


def iscoroutinefunction(func: Callable):
    return inspect.iscoroutinefunction(func)


def run_async(func, *args, **kwargs):
    """Generalized asyncio.run for jupyter notebook.

    When running inside jupyter, an eventloop is already exist, can't be stopped, can't be killed.
    Directly calling asyncio.run will fail, as This function cannot be called when another asyncio event loop
    is running in the same thread.

    .. see_also:
        https://stackoverflow.com/questions/55409641/asyncio-run-cannot-be-called-from-a-running-event-loop

    call `run_async(my_function, any_event_loop=True, *args, **kwargs)` to enable run with any eventloop

    :param func: function to run
    :param args: parameters
    :param kwargs: key-value parameters
    :return: asyncio.run(func)
    """

    any_event_loop = kwargs.pop("any_event_loop", False)

    class _RunThread(threading.Thread):
        """Create a running thread when in Jupyter notebook."""

        def run(self):
            """Run given `func` asynchronously."""
            self.result = asyncio.run(func(*args, **kwargs))

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # eventloop already exist
        # running inside Jupyter
        if any_event_loop or is_jupyter():
            thread = _RunThread()
            thread.start()
            thread.join()
            try:
                return thread.result
            except AttributeError:
                from marie.excepts import BadClient

                raise BadClient("something wrong when running the eventloop, result can not be retrieved")
        else:

            raise RuntimeError(
                "you have an eventloop running but not using Jupyter/ipython, "
                "this may mean you are using Jina with other integration? if so, then you "
                "may want to use Client/Flow(asyncio=True). If not, then "
                "please report this issue here: https://github.com/jina-ai/jina"
            )
    else:
        return get_or_reuse_loop().run_until_complete(func(*args, **kwargs))


def slugify(value):
    """
    Normalize string, converts to lowercase, removes non-alpha characters, and converts spaces to hyphens.

    :param value: Original string.
    :return: Processed string.
    """
    s = str(value).strip().replace(" ", "_")
    return re.sub(r"(?u)[^-\w.]", "", s)


def is_yaml_filepath(val) -> bool:
    """
    Check if the file is YAML file.

    :param val: Path of target file.
    :return: True if the file is YAML else False.
    """
    if __windows__:
        r = r".*.ya?ml$"  # TODO: might not be exhaustive
    else:
        r = r"^[/\w\-\_\.]+.ya?ml$"
    return re.match(r, val.strip()) is not None


if TYPE_CHECKING:
    from fastapi import FastAPI


def extend_rest_interface(app: "FastAPI") -> "FastAPI":
    """Extend Marie built-in FastAPI instance with customized APIs, routing, etc.

    :param app: the built-in FastAPI instance given by Marie
    :return: the extended FastAPI instance

    .. highlight:: python
    .. code-block:: python

        def extend_rest_interface(app: 'FastAPI'):
            @app.get('/extension1')
            async def root():
                return {"message": "Hello World"}

            return app
    """
    return app


def get_full_version() -> Optional[Tuple[Dict, Dict]]:
    """
    Get the version of libraries used in Marie and environment variables.

    :return: Version information and environment variables
    """
    import os
    import platform
    from uuid import getnode

    import yaml

    from marie.version import __version__
    from marie import (
        __docarray_version__,
        __marie_env__,
        __unset_msg__,
        __uptime__,
    )
    from marie.logging.predefined import default_logger

    try:

        info = {
            "marie": __version__,
            "docarray": __docarray_version__,
            "pyyaml": yaml.__version__,
            "python": platform.python_version(),
            "platform": platform.system(),
            "platform-release": platform.release(),
            "platform-version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "uid": getnode(),
            "session-id": str(random_uuid(use_uuid1=True)),
            "uptime": __uptime__,
        }

        env_info = {k: os.getenv(k, __unset_msg__) for k in __marie_env__}
        full_version = info, env_info
    except Exception as e:
        default_logger.error(str(e))
        full_version = None

    return full_version


def format_full_version_info(info: Dict, env_info: Dict) -> str:
    """
    Format the version information.

    :param info: Version information of Marie libraries.
    :param env_info: The Marie environment variables.
    :return: Formatted version information.
    """
    version_info = "\n".join(f"- {k:30s}{v}" for k, v in info.items())
    env_info = "\n".join(f"* {k:30s}{v}" for k, v in env_info.items())
    return version_info + "\n" + env_info


def _update_policy():
    if __windows__:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    elif "MARIE_DISABLE_UVLOOP" in os.environ:
        return
    else:
        try:
            import uvloop

            if not isinstance(asyncio.get_event_loop_policy(), uvloop.EventLoopPolicy):
                asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        except ModuleNotFoundError:
            warnings.warn('Install `uvloop` via `pip install "marie[uvloop]"` for better performance.')


def _close_loop():
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.close()
    except RuntimeError:
        # there is no loop, so nothing to do here
        pass


# workaround for asyncio loop and fork issue: https://github.com/python/cpython/issues/66197
# we close the loop after forking to avoid reusing the parents process loop
# a new loop should be created in the child process
os.register_at_fork(after_in_child=_close_loop)


def get_or_reuse_loop():
    """
    Get a new eventloop or reuse the current opened eventloop.

    :return: A new eventloop or reuse the current opened eventloop.
    """
    _update_policy()
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        # no event loop
        # create a new loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def typename(obj):
    """
    Get the typename of object.

    :param obj: Target object.
    :return: Typename of the obj.
    """
    if not isinstance(obj, type):
        obj = obj.__class__
    try:
        return f"{obj.__module__}.{obj.__name__}"
    except AttributeError:
        return str(obj)


class CatchAllCleanupContextManager:
    """
    This context manager guarantees, that the :method:``__exit__`` of the
    sub context is called, even when there is an Exception in the
    :method:``__enter__``.

    :param sub_context: The context, that should be taken care of.
    """

    def __init__(self, sub_context):
        self.sub_context = sub_context

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.sub_context.__exit__(exc_type, exc_val, exc_tb)


def random_identity(use_uuid1: bool = False) -> str:
    """
    Generate random UUID.

    ..note::
        A MAC address or time-based ordering (UUID1) can afford increased database performance, since it's less work
        to sort numbers closer-together than those distributed randomly (UUID4) (see here).

        A second related issue, is that using UUID1 can be useful in debugging, even if origin data is lost or not
        explicitly stored.

    :param use_uuid1: use UUID1 instead of UUID4. This is the default Document ID generator.
    :return: A random UUID.

    """
    return random_uuid(use_uuid1).hex


def random_uuid(use_uuid1: bool = False) -> uuid.UUID:
    """
    Get a random UUID.

    :param use_uuid1: Use UUID1 if True, else use UUID4.
    :return: A random UUID.
    """
    return uuid.uuid1() if use_uuid1 else uuid.uuid4()


def expand_env_var(v: str) -> Optional[Union[bool, int, str, list, float]]:
    """
    Expand the environment variables.

    :param v: String of environment variables.
    :return: Parsed environment variables.
    """
    if isinstance(v, str):
        return parse_arg(os.path.expandvars(v))
    else:
        return v


_ATTRIBUTES = {
    "bold": 1,
    "dark": 2,
    "underline": 4,
    "blink": 5,
    "reverse": 7,
    "concealed": 8,
}

_HIGHLIGHTS = {
    "on_grey": 40,
    "on_red": 41,
    "on_green": 42,
    "on_yellow": 43,
    "on_blue": 44,
    "on_magenta": 45,
    "on_cyan": 46,
    "on_white": 47,
}

_COLORS = {
    "black": 30,
    "red": 31,
    "green": 32,
    "yellow": 33,
    "blue": 34,
    "magenta": 35,
    "cyan": 36,
    "white": 37,
}

_RESET = "\033[0m"

if __windows__:
    os.system("color")


def colored(
    text: str,
    color: Optional[str] = None,
    on_color: Optional[str] = None,
    attrs: Optional[Union[str, list]] = None,
) -> str:
    """
    Give the text with color.

    :param text: The target text.
    :param color: The color of text. Chosen from the following.
        {
            'grey': 30,
            'red': 31,
            'green': 32,
            'yellow': 33,
            'blue': 34,
            'magenta': 35,
            'cyan': 36,
            'white': 37
        }
    :param on_color: The on_color of text. Chosen from the following.
        {
            'on_grey': 40,
            'on_red': 41,
            'on_green': 42,
            'on_yellow': 43,
            'on_blue': 44,
            'on_magenta': 45,
            'on_cyan': 46,
            'on_white': 47
        }
    :param attrs: Attributes of color. Chosen from the following.
        {
           'bold': 1,
           'dark': 2,
           'underline': 4,
           'blink': 5,
           'reverse': 7,
           'concealed': 8
        }
    :return: Colored text.
    """
    if "MARIE_LOG_NO_COLOR" not in os.environ:
        fmt_str = "\033[%dm%s"
        if color:
            text = fmt_str % (_COLORS[color], text)
        if on_color:
            text = fmt_str % (_HIGHLIGHTS[on_color], text)

        if attrs:
            if isinstance(attrs, str):
                attrs = [attrs]
            if isinstance(attrs, list):
                for attr in attrs:
                    text = fmt_str % (_ATTRIBUTES[attr], text)
        text += _RESET
    return text


def colored_rich(
    text: str,
    color: Optional[str] = None,
    on_color: Optional[str] = None,
    attrs: Optional[Union[str, list]] = None,
) -> str:
    """
    Give the text with color. You should only use it when printing with rich print. Othersiwe please see the colored
    function

    :param text: The target text
    :param color: The color of text
    :param on_color: The on color of text: ex on yellow
    :param attrs: Attributes of color

    :return: Colored text.
    """
    if "MARIE_LOG_NO_COLOR" not in os.environ:
        if color:
            text = _wrap_text_in_rich_bracket(text, color)
        if on_color:
            text = _wrap_text_in_rich_bracket(text, on_color)

        if attrs:
            if isinstance(attrs, str):
                attrs = [attrs]
            if isinstance(attrs, list):
                for attr in attrs:
                    text = _wrap_text_in_rich_bracket(text, attr)
    return text


def _wrap_text_in_rich_bracket(text: str, wrapper: str):
    return f"[{wrapper}]{text}[/{wrapper}]"


def warn_unknown_args(unknown_args: List[str]):
    """Creates warnings for all given arguments.

    :param unknown_args: arguments that are possibly unknown to Marie
    """
    pass


class ArgNamespace:
    """Helper function for argparse.Namespace object."""

    @staticmethod
    def kwargs2list(kwargs: Dict) -> List[str]:
        """
        Convert dict to an argparse-friendly list.

        :param kwargs: dictionary of key-values to be converted
        :return: argument list
        """
        args = []
        from marie.serve.executors import BaseExecutor

        for k, v in kwargs.items():
            k = k.replace('_', '-')
            if v is not None:
                if isinstance(v, bool):
                    if v:
                        args.append(f'--{k}')
                elif isinstance(v, list):  # for nargs
                    args.extend([f'--{k}', *(str(vv) for vv in v)])
                elif isinstance(v, dict):
                    args.extend([f'--{k}', json.dumps(v)])
                elif isinstance(v, type) and issubclass(v, BaseExecutor):
                    args.extend([f'--{k}', v.__name__])
                else:
                    args.extend([f'--{k}', str(v)])
        return args

    @staticmethod
    def kwargs2namespace(
        kwargs: Dict[str, Union[str, int, bool]],
        parser: ArgumentParser,
        warn_unknown: bool = False,
        fallback_parsers: Optional[List[ArgumentParser]] = None,
        positional_args: Optional[Tuple[str, ...]] = None,
    ) -> Namespace:
        """
        Convert dict to a namespace.

        :param kwargs: dictionary of key-values to be converted
        :param parser: the parser for building kwargs into a namespace
        :param warn_unknown: True, if unknown arguments should be logged
        :param fallback_parsers: a list of parsers to help resolving the args
        :param positional_args: some parser requires positional arguments to be presented
        :return: argument list
        """
        args = ArgNamespace.kwargs2list(kwargs)
        if positional_args:
            args += positional_args
        p_args, unknown_args = parser.parse_known_args(args)
        unknown_args = list(filter(lambda x: x.startswith('--'), unknown_args))
        if warn_unknown and unknown_args:
            _leftovers = set(unknown_args)
            if fallback_parsers:
                for p in fallback_parsers:
                    _, _unk_args = p.parse_known_args(args)
                    _leftovers = _leftovers.intersection(_unk_args)
                    if not _leftovers:
                        # all args have been resolved
                        break
            warn_unknown_args(_leftovers)

        return p_args

    @staticmethod
    def get_non_defaults_args(
        args: Namespace, parser: ArgumentParser, taboo: Optional[Set[str]] = None
    ) -> Dict:
        """
        Get non-default args in a dict.

        :param args: the namespace to parse
        :param parser: the parser for referring the default values
        :param taboo: exclude keys in the final result
        :return: non defaults
        """
        if taboo is None:
            taboo = set()
        non_defaults = {}
        _defaults = vars(parser.parse_args([]))
        for k, v in vars(args).items():
            if k in _defaults and k not in taboo and _defaults[k] != v:
                non_defaults[k] = v
        return non_defaults

    @staticmethod
    def flatten_to_dict(
        args: Union[Dict[str, 'Namespace'], 'Namespace']
    ) -> Dict[str, Any]:
        """Convert argparse.Namespace to dict to be uploaded via REST.

        :param args: namespace or dict or namespace to dict.
        :return: pod args
        """
        if isinstance(args, Namespace):
            return vars(args)
        elif isinstance(args, dict):
            pod_args = {}
            for k, v in args.items():
                if isinstance(v, Namespace):
                    pod_args[k] = vars(v)
                elif isinstance(v, list):
                    pod_args[k] = [vars(_) for _ in v]
                else:
                    pod_args[k] = v
            return pod_args


def get_rich_console():
    """
    Function to get jina rich default console.
    :return: rich console
    """
    return Console(
        force_terminal=True if "PYCHARM_HOSTED" in os.environ else None,
        color_system=None if "MARIE_LOG_NO_COLOR" in os.environ else "auto",
    )


def get_readable_time(*args, **kwargs):
    """
    Get the datetime in human readable format (e.g. 115 days and 17 hours and 46 minutes and 40 seconds).

    For example:
        .. highlight:: python
        .. code-block:: python
            get_readable_time(seconds=1000)

    :param args: arguments for datetime.timedelta
    :param kwargs: key word arguments for datetime.timedelta
    :return: Datetime in human readable format.
    """
    import datetime

    secs = float(datetime.timedelta(*args, **kwargs).total_seconds())
    units = [("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1)]
    parts = []
    for unit, mul in units:
        if secs / mul >= 1 or mul == 1:
            if mul > 1:
                n = int(math.floor(secs / mul))
                secs -= n * mul
            else:
                n = int(secs)
            parts.append(f"{n} {unit}" + ("" if n == 1 else "s"))
    return " and ".join(parts)


def get_readable_size(num_bytes: Union[int, float]) -> str:
    """
    Transform the bytes into readable value with different units (e.g. 1 KB, 20 MB, 30.1 GB).

    :param num_bytes: Number of bytes.
    :return: Human readable string representation.
    """
    num_bytes = int(num_bytes)
    if num_bytes < 1024:
        return f"{num_bytes} Bytes"
    elif num_bytes < 1024**2:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024**3:
        return f"{num_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{num_bytes / (1024 ** 3):.1f} GB"


def batch_iterator(
    data: Iterable[Any],
    batch_size: int,
    axis: int = 0,
) -> Iterator[Any]:
    """
    Get an iterator of batches of data.

    For example:
    .. highlight:: python
    .. code-block:: python

            for req in batch_iterator(data, batch_size, split_over_axis):
                pass  # Do something with batch

    :param data: Data source.
    :param batch_size: Size of one batch.
    :param axis: Determine which axis to iterate for np.ndarray data.
    :yield: data
    :return: An Iterator of batch data.
    """
    import numpy as np

    if not batch_size or batch_size <= 0:
        yield data
        return
    if isinstance(data, np.ndarray):
        _l = data.shape[axis]
        _d = data.ndim
        sl = [slice(None)] * _d
        if batch_size >= _l:
            yield data
            return
        for start in range(0, _l, batch_size):
            end = min(_l, start + batch_size)
            sl[axis] = slice(start, end)
            yield data[tuple(sl)]
    elif isinstance(data, Sequence):
        if batch_size >= len(data):
            yield data
            return
        for _ in range(0, len(data), batch_size):
            yield data[_ : _ + batch_size]
    elif isinstance(data, Iterable):
        # as iterator, there is no way to know the length of it
        iterator = iter(data)
        while True:
            chunk = tuple(islice(iterator, batch_size))
            if not chunk:
                return
            yield chunk
    else:
        raise TypeError(f"unsupported type: {type(data)}")


def parse_arg(v: str) -> Optional[Union[bool, int, str, list, float]]:
    """
    Parse the arguments from string to `Union[bool, int, str, list, float]`.

    :param v: The string of arguments
    :return: The parsed arguments list.
    """
    m = re.match(r'^[\'"](.*)[\'"]$', v)
    if m:
        return m.group(1)

    if v.startswith("[") and v.endswith("]"):
        # function args must be immutable tuples not list
        tmp = v.replace("[", "").replace("]", "").strip().split(",")
        if len(tmp) > 0:
            return [parse_arg(vv.strip()) for vv in tmp]
        else:
            return []
    try:
        v = int(v)  # parse int parameter
    except ValueError:
        try:
            v = float(v)  # parse float parameter
        except ValueError:
            if len(v) == 0:
                # ignore it when the parameter is empty
                v = None
            elif v.lower() == "true":  # parse boolean parameter
                v = True
            elif v.lower() == "false":
                v = False
    return v


assigned_ports = set()
unassigned_ports = []
DEFAULT_MIN_PORT = 49153
MAX_PORT = 65535


def reset_ports():
    def _get_unassigned_ports():
        # if we are running out of ports, lower default minimum port
        if MAX_PORT - DEFAULT_MIN_PORT - len(assigned_ports) < 100:
            min_port = int(os.environ.get("JINA_RANDOM_PORT_MIN", "16384"))
        else:
            min_port = int(os.environ.get("JINA_RANDOM_PORT_MIN", str(DEFAULT_MIN_PORT)))
        max_port = int(os.environ.get("JINA_RANDOM_PORT_MAX", str(MAX_PORT)))
        return set(range(min_port, max_port + 1)) - set(assigned_ports)

    unassigned_ports.clear()
    assigned_ports.clear()
    unassigned_ports.extend(_get_unassigned_ports())
    random.shuffle(unassigned_ports)


def random_port() -> Optional[int]:
    """
    Get a random available port number.

    :return: A random port.
    """

    def _random_port():
        import socket

        def _check_bind(port):
            with socket.socket() as s:
                try:
                    s.bind(("", port))
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    return port
                except OSError:
                    return None

        _port = None
        if len(unassigned_ports) == 0:
            reset_ports()
        for idx, _port in enumerate(unassigned_ports):
            if _check_bind(_port) is not None:
                break
        else:
            raise OSError(
                f"can not find an available port in {len(unassigned_ports)} unassigned ports, assigned already {len(assigned_ports)} ports"
            )
        int_port = int(_port)
        unassigned_ports.pop(idx)
        assigned_ports.add(int_port)
        return int_port

    try:
        return _random_port()
    except OSError:
        assigned_ports.clear()
        unassigned_ports.clear()
        return _random_port()
