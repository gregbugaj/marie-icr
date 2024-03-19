import os
from typing import List, Optional, Tuple, Union

import numpy as np
import torch
from docarray import DocList
from docarray.base_doc.doc import BaseDocWithoutId
from pydantic import BaseModel

from marie import Executor, requests, safely_encoded
from marie.api.docs import AssetKeyDoc, BaseDoc
from marie.components.template_matching.model import TemplateMatchResult
from marie.logging.logger import MarieLogger
from marie.logging.predefined import default_logger as logger
from marie.models.utils import setup_torch_optimizations
from marie.utils.docs import docs_from_asset, frames_from_docs
from marie.utils.network import get_ip_address


class TemplateMatchResultDoc(BaseDocWithoutId, frozen=True):
    bbox: Tuple[int, int, int, int]
    label: str
    score: float
    similarity: float
    frame_index: Optional[int] = 0


class TemplateMatchingResultDoc(BaseDoc, frozen=True):
    asset_key: str
    results: List[TemplateMatchResultDoc]


class TemplateSelector(BaseDocWithoutId, frozen=True):
    region: List[int]
    frame: str
    bbox: List[int]
    label: str
    text: str
    create_window: bool
    top_k: int


class TemplateMatchingRequestDoc(BaseDoc):
    asset_key: str
    id: str
    pages: List[int]
    score_threshold: float
    scoring_strategy: str
    max_overlap: float
    window_size: List[int]
    matcher: str
    downscale_factor: int
    selectors: List[TemplateSelector]


def convert_to_protobuf_doc(match: TemplateMatchResult) -> TemplateMatchResultDoc:
    """
    Convert a TemplateMatchResult to a TemplateMatchResultDoc
    :param match:
    :return: protobuf serializable TemplateMatchResultDoc
    """
    return TemplateMatchResultDoc(
        bbox=match.bbox,
        label=match.label,
        score=match.score,
        similarity=match.similarity,
        frame_index=match.frame_index,
    )


class TemplateMatchingExecutor(Executor):
    def __init__(
        self,
        name: str = "",
        device: Optional[str] = None,
        num_worker_preprocess: int = 4,
        pipeline: Optional[dict[str, any]] = None,
        dtype: Optional[Union[str, torch.dtype]] = None,
        **kwargs,
    ):
        """
        :param device: 'cpu' or 'cuda'. Default is None, which auto-detects the device.
        :param num_worker_preprocess: The number of CPU workers to preprocess images and texts. Default is 4.
        :param minibatch_size: The size of the minibatch for preprocessing and encoding. Default is 32. Reduce this
            number if you encounter OOM errors.
        :param dtype: inference data type, if None defaults to torch.float32 if device == 'cpu' else torch.float16.
        """
        super().__init__(**kwargs)
        import time

        logger.info(f"Starting mock executor : {time.time()}")
        setup_torch_optimizations()

        self.show_error = True  # show prediction errors
        # sometimes we have CUDA/GPU support but want to only use CPU
        use_cuda = torch.cuda.is_available()
        if os.environ.get("MARIE_DISABLE_CUDA"):
            use_cuda = False
        self.logger = MarieLogger(context=self.__class__.__name__)

        if not device:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if not use_cuda:
            device = "cpu"
        self.device = device

        self.runtime_info = {
            "name": self.__class__.__name__,
            "instance_name": kwargs.get("runtime_args", {}).get("name", "not_defined"),
            "model": "",
            "host": get_ip_address(),
            "workspace": self.workspace,
            "use_cuda": use_cuda,
            "device": self.device.__str__() if self.device is not None else "",
        }

        logger.info(f"Runtime info: {self.runtime_info}")
        logger.info(f"Pipeline : {pipeline}")

    @requests(on="/document/matcher")
    def match(
        self,
        docs: DocList[TemplateMatchingRequestDoc],
        parameters: dict,
        *args,
        **kwargs,
    ):
        print("TEMPLATE MATCHING EXECUTOR")
        print(parameters)
        print(docs)

        logger.info(kwargs)
        logger.info(parameters)

        print("Dumping docs:")
        for doc in docs:
            print(doc)

        tmr = TemplateMatchResult(
            bbox=(10, 20, 40, 100),
            label="LABELA ABC",
            score=0.9,
            similarity=0.6,
            frame_index=0,
        )

        reply = DocList[TemplateMatchingResultDoc]()

        reply.append(
            TemplateMatchingResultDoc(
                asset_key="RETURN_ASSET_KEY",
                results=[
                    convert_to_protobuf_doc(tmr),
                    convert_to_protobuf_doc(tmr),
                ],
            )
        )

        return reply

        if len(docs) == 0:
            return {"error": "empty payload"}
        if len(docs) > 1:
            return {"error": "expected single document"}

        doc = docs[0]
        # load documents from specified document asset key
        docs = docs_from_asset(doc.asset_key, doc.pages)

        for doc in docs:
            print(doc.id)

        frames = frames_from_docs(docs)
        frame_len = len(frames)

        print(f"{frame_len=}")

        import time

        if "payload" not in parameters or parameters["payload"] is None:
            return {"error": "empty payload"}
        else:
            payload = parameters["payload"]
        regions = payload["regions"] if "regions" in payload else []
        for region in regions:
            region["id"] = int(region["id"])
            region["pageIndex"] = int(region["pageIndex"])

        np_arr = np.array([1, 2, 3])
        out = [
            {"sample": 112, "complex": ["a", "b"]},
            {"sample": 112, "complex": ["a", "b"], "np_arr": np_arr},
        ]

        time.sleep(1)
        # invoke the safely_encoded decorator as a function
        meta = get_ip_address()
        #  DocList / Dict / `None`
        converted = safely_encoded(lambda x: x)(self.runtime_info)
        return converted
