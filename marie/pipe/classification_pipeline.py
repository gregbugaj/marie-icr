import os
import shutil
import types
from datetime import datetime
from typing import List, Optional, Union

import numpy as np
from docarray import DocList
from PIL import Image

from marie.boxes import PSMode
from marie.excepts import BadConfigSource
from marie.logging.logger import MarieLogger
from marie.models.utils import initialize_device_settings
from marie.ocr import CoordinateFormat
from marie.ocr.util import get_known_ocr_engines, get_words_and_boxes
from marie.pipe import (
    ClassifierPipelineComponent,
    NamedEntityPipelineComponent,
    PipelineComponent,
    PipelineContext,
)
from marie.pipe.components import (
    burst_frames,
    load_pipeline,
    ocr_frames,
    reload_pipeline,
    restore_assets,
    store_assets,
    store_metadata,
)
from marie.pipe.voting import ClassificationResult, get_voting_strategy
from marie.utils.docs import docs_from_image
from marie.utils.image_utils import hash_frames_fast
from marie.utils.utils import ensure_exists


class ClassificationPipeline:
    """
    Classification pipeline for documents.

    The pipeline will perform the following operations on the document:
    - Burst the document, if it is a multi-page document into individual pages
    - Perform OCR on the document pages
    - Classify the document pages

    Example usage:
        .. code-block:: python

            pipeline_config = load_yaml(
                os.path.join(
                    __config_dir__, "tests-integration", "pipeline-integration.partial.yml"
                )
            )
            pipeline = ClassificationPipeline(pipeline_config=pipeline_config["pipeline"])

            with TimeContext(f"### ExtractPipeline info"):
                results = pipeline.execute(
                    ref_id=filename, ref_type="pid", frames=frames_from_file(img_path)
                )
    """

    def __init__(
        self,
        pipelines_config: List[dict[str, any]] = None,
        device: Optional[str] = "cuda",
        silence_exceptions: bool = False,
        **kwargs,
    ) -> None:
        self.show_error = True  # show prediction errors
        self.logger = MarieLogger(context=self.__class__.__name__)
        self.load_pipeline = types.MethodType(load_pipeline, self)

        self.pipelines_config = pipelines_config
        self.reload_pipeline = types.MethodType(reload_pipeline, self)
        self.default_pipeline_config = None
        self.silence_exceptions = silence_exceptions

        for conf in pipelines_config:
            conf = conf["pipeline"]
            if conf.get("default", False):
                if self.default_pipeline_config is not None:
                    raise BadConfigSource(
                        "Invalid pipeline configuration, multiple defaults found"
                    )
                self.default_pipeline_config = conf

        if self.default_pipeline_config is None:
            raise BadConfigSource("Invalid pipeline configuration, default not found")

        # sometimes we have CUDA/GPU support but want to only use CPU
        resolved_devices, _ = initialize_device_settings(
            devices=[device], use_cuda=True, multi_gpu=False
        )
        if len(resolved_devices) > 1:
            self.logger.warning(
                "Multiple devices are not supported in %s inference, using the first device %s.",
                self.__class__.__name__,
                resolved_devices[0],
            )
        self.device = resolved_devices[0]
        has_cuda = True if self.device.type.startswith("cuda") else False

        self.ocr_engines = get_known_ocr_engines(
            device=self.device.type, engine="default"
        )
        (
            self.pipeline_name,
            self.classifier_groups,
            self.document_indexers,
        ) = self.load_pipeline(
            self.default_pipeline_config, self.ocr_engines["default"]
        )

    def execute_frames_pipeline(
        self,
        ref_id: str,
        ref_type: str,
        frames: List[np.ndarray],
        root_asset_dir: str,
        job_id: str,
        runtime_conf: Optional[dict[str, any]] = None,
    ) -> dict[str, any]:
        if ref_type is None or ref_id is None:
            raise ValueError("Invalid reference type or id")

        self.logger.info(
            f"Executing pipeline for document : {ref_id}, {ref_type} > {root_asset_dir}"
        )
        self.logger.info(f"Executing pipeline runtime_conf : {runtime_conf}")

        page_classifier_enabled = runtime_conf.get("page_classifier", {}).get(
            "enabled", True
        )

        # check if the current pipeline name is the default pipeline name
        if "name" in runtime_conf:
            expected_pipeline_name = runtime_conf["name"]
            if expected_pipeline_name != self.pipeline_name:
                self.logger.warning(
                    f"pipeline name : {expected_pipeline_name}, expected : {self.pipeline_name} , reloading pipeline"
                )
                self.reload_pipeline(expected_pipeline_name)

        page_indexer_enabled = runtime_conf.get("page_indexer", {}).get("enabled", True)

        self.logger.info(
            f"Feature : page classifier enabled : {page_classifier_enabled}"
        )
        self.logger.info(f"Feature : page indexer enabled : {page_indexer_enabled}")

        for group, classifiers in self.classifier_groups.items():
            self.logger.info(f"Loaded classifiers : {group}, {len(classifiers)}")

        metadata = {
            "ref_id": ref_id,
            "ref_type": ref_type,
            "job_id": job_id,
            "pipeline": self.pipeline_name,
            "pages": f"{len(frames)}",
        }

        restore_assets(
            ref_id, ref_type, root_asset_dir, full_restore=False, overwrite=True
        )
        burst_frames(ref_id, frames, root_asset_dir)
        ocr_results = ocr_frames(self.ocr_engines, ref_id, frames, root_asset_dir)

        metadata["ocr"] = ocr_results
        metadata["classifications"] = []
        metadata["indexers"] = []

        # TODO : Need to refactor this
        for group, classifier_group in self.classifier_groups.items():
            self.logger.info(
                f"Processing classifier pipeline/group :  {self.pipeline_name}, {group}"
            )
            document_classifiers = classifier_group["classifiers"]
            sub_classifiers = classifier_group["sub_classifiers"]

            processing_pipeline = [
                ClassifierPipelineComponent(
                    name="classifier_pipeline",
                    document_classifiers=document_classifiers,
                )
            ]

            if page_indexer_enabled:
                processing_pipeline.append(
                    NamedEntityPipelineComponent(
                        name="ner_pipeline_component",
                        document_indexers=self.document_indexers,
                    )
                )

            results = self.execute_pipeline(
                processing_pipeline, sub_classifiers, frames, ocr_results
            )

            metadata["classifications"].append(
                {
                    "group": group,
                    "classification": results["classifier"]
                    if "classifier" in results
                    else {},
                }
            )

            metadata["indexers"].append(
                {
                    "group": group,
                    "indexer": results["indexer"] if "indexer" in results else {},
                }
            )

        store_metadata(ref_id, ref_type, root_asset_dir, metadata)
        store_assets(ref_id, ref_type, root_asset_dir, match_wildcard="*.json")
        del metadata["ocr"]

        return metadata

    def execute(
        self,
        ref_id: str,
        ref_type: str,
        frames: Union[List[np.ndarray], List[Image.Image]],
        pms_mode: PSMode = PSMode.SPARSE,
        coordinate_format: CoordinateFormat = CoordinateFormat.XYWH,
        regions: List = None,
        queue_id: str = None,
        job_id: str = None,
        runtime_conf: Optional[dict[str, any]] = None,
    ) -> dict[str, any]:
        """
        Execute the pipeline for the document with the given frames.If regions are specified,
        then only the specified regions will be extracted from the document with the rest of the steps being skipped.

        By default, this will perform the following steps

        2. Burst the document
        3. Perform OCR on the document
        5. Classify the document
        6. Store the results in the backend store(s3 , redis, etc.)

        :param ref_id:  reference id of the document (e.g. file name)
        :param ref_type: reference type of the document (e.g. invoice, receipt, etc)
        :param frames: frames to process for the document
        :param pms_mode:  Page segmentation mode for OCR default is SPARSE
        :param coordinate_format: coordinate format for OCR default is XYWH
        :param queue_id:  queue id to associate with the document
        :param job_id: job id to associate with the document
        :param runtime_conf: runtime configuration for the pipeline (e.g. which steps to execute) default is None.
        :return:  metadata for the document (e.g. OCR results, classification results, etc)
        """

        # create local asset directory
        frame_checksum = hash_frames_fast(frames=frames)
        # create backup name by appending a timestamp
        # TODO : Need to refactor this
        if False:  # os.path.exists(os.path.join("/tmp/generators", frame_checksum)):
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            shutil.move(
                os.path.join("/tmp/generators", frame_checksum),
                os.path.join("/tmp/generators", f"{frame_checksum}-{ts}"),
            )

        root_asset_dir = ensure_exists(os.path.join("/tmp/generators", frame_checksum))

        self.logger.info(f"Root asset dir {ref_id}, {ref_type} : {root_asset_dir}")
        self.logger.info(f"runtime_conf args : {runtime_conf}")

        if runtime_conf is None:
            self.logger.warning("runtime_conf is None, using default config")
            runtime_conf = {}

        return self.execute_frames_pipeline(
            ref_id, ref_type, frames, root_asset_dir, job_id, runtime_conf
        )

    def execute_pipeline(
        self,
        processing_pipeline: List[PipelineComponent],
        sub_classifiers: dict[str, any],
        frames: List,
        ocr_results: dict,
    ) -> dict[str, any]:
        """Execute processing pipeline"""

        words = []
        boxes = []
        documents = docs_from_image(frames)
        assert len(documents) == len(frames)

        for page_idx in range(len(frames)):
            page_words, page_boxes = get_words_and_boxes(ocr_results, page_idx)
            words.append(page_words)
            boxes.append(page_boxes)

        assert len(words) == len(boxes)

        context = PipelineContext(pipeline_id="classification_pipeline")
        context["metadata"] = {}

        for pipe in processing_pipeline:
            try:
                # create a PipelineContext and pass it to the component
                pipe_results = pipe.run(documents, context, words=words, boxes=boxes)
                if pipe_results.state is not None:
                    if not isinstance(pipe_results.state, DocList):
                        raise ValueError(
                            f"Invalid state type : {type(pipe_results.state)}"
                        )
                    documents = pipe_results.state
            except Exception as e:
                if not self.silence_exceptions:
                    raise ValueError("Error executing pipe") from e
                self.logger.error(f"Error executing pipe : {e}")

        # TODO : This is temporary, we need to make this configurable
        self.logger.info("### ClassificationPipeline results")
        self.logger.info(context["metadata"])

        page_indexer_meta = (
            context["metadata"]["page_indexer"]
            if "page_indexer" in context["metadata"]
            else []
        )
        page_classifier_meta = (
            context["metadata"]["page_classifier"]
            if "page_classifier" in context["metadata"]
            else []
        )

        for idx, page_result in enumerate(page_classifier_meta):
            for detail in page_result["details"]:
                page = int(detail["page"])
                classification = detail["classification"]
                filtered_classifiers = {}

                for key, val in sub_classifiers.items():
                    fileter_config = val["filter"]
                    filter_type = fileter_config["type"]
                    filter_pattern = fileter_config["pattern"]

                    if filter_type == "exact" and classification == filter_pattern:
                        self.logger.info(f"Adding sub-classifier : {key}")
                        filtered_classifiers[key] = val

                if filtered_classifiers:
                    self.logger.info(
                        f"Filtered classifiers : {filtered_classifiers.keys()}"
                    )
                    sub_classifier_pipeline = ClassifierPipelineComponent(
                        name="sub_classifier_pipeline",
                        document_classifiers=filtered_classifiers,
                    )

                    ctx = PipelineContext(pipeline_id="sub_classification_pipeline")
                    ctx["metadata"] = {}
                    pipe_results = sub_classifier_pipeline.run(
                        documents[page : page + 1],
                        ctx,
                        words=[words[page]],
                        boxes=[boxes[page]],
                    )
                    detail["sub_classifier"] = ctx["metadata"]["page_classifier"]

        # TODO : Read from config
        # Classification strategy: max_score, max_votes, max_score_with_diff
        prediction_agent = "majority"
        tie_break_policy = "best_with_diff"
        voter = get_voting_strategy(prediction_agent, tie_break_policy, max_diff=0.25)

        class_by_page = self.group_results_by_page("classifier", page_classifier_meta)
        score_by_page = {}
        for page, details in class_by_page.items():
            score_by_page[page] = voter([ClassificationResult(**x) for x in details])

        classifier_results = {
            "strategy": prediction_agent,
            "tie_break_policy": tie_break_policy,
            "pages": {},
        }

        for page in list(class_by_page.keys()):
            classifier_results["pages"][page] = {
                "details": class_by_page[page],
                "best": score_by_page[page],
            }

        # Indexer results
        indexer_by_page = self.group_results_by_page("indexer", page_indexer_meta)
        indexer_results = {"strategy": "default", "pages": {}}

        for page in list(indexer_by_page.keys()):
            indexer_results["pages"][page] = {"details": indexer_by_page[page]}

        return {"classifier": classifier_results, "indexer": indexer_results}

    def group_results_by_page(self, group_key: str, page_meta: List[dict[str, any]]):
        """Group the results by page"""
        group_by_page = {}
        for idx, page_result in enumerate(page_meta):
            indexer = page_result[group_key]
            for detail in page_result["details"]:
                page = int(detail["page"])
                if page not in group_by_page:
                    group_by_page[page] = []
                detail[group_key] = indexer
                group_by_page[page].append(detail)

        return group_by_page
