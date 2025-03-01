import time
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Union

import cv2
import numpy as np
import sahi.annotation as BoundingBox
from PIL import Image
from sahi.postprocess.combine import (
    GreedyNMMPostprocess,
    LSNMSPostprocess,
    NMMPostprocess,
    NMSPostprocess,
)
from sahi.prediction import ObjectPrediction, PredictionScore
from sahi.slicing import slice_image

from marie.components.template_matching.model import TemplateMatchResult
from marie.logging_core.logger import MarieLogger
from marie.models.utils import torch_gc
from marie.ocr.util import get_words_and_boxes
from marie.utils.resize_image import resize_image_progressive

POSTPROCESS_NAME_TO_CLASS = {
    "GREEDYNMM": GreedyNMMPostprocess,
    "NMM": NMMPostprocess,
    "NMS": NMSPostprocess,
    "LSNMS": LSNMSPostprocess,
}


class BaseTemplateMatcher(ABC):
    """
    BaseTemplateMatcher is used to match a template in an image.
    """

    DEFAULT_OVERLAP_HEIGHT_RATIO = 0.2
    DEFAULT_OVERLAP_WIDTH_RATIO = 0.2

    def __init__(
        self,
        slicing_enabled: bool = True,
        **kwargs,
    ) -> None:
        self.logger = MarieLogger(self.__class__.__name__).logger
        self.slicing_enabled = slicing_enabled

    @abstractmethod
    def predict(
        self,
        frame: np.ndarray,
        template_frames: list[np.ndarray],
        template_boxes: list[tuple[int, int, int, int]],
        template_labels: list[str],
        template_texts: list[str] = None,
        score_threshold: float = 0.9,
        scoring_strategy: str = "weighted",  # "weighted" or "average"
        max_objects: int = 1,
        batch_size: int = 1,
        words: list[str] = None,
        word_boxes: list[tuple[int, int, int, int]] = None,
        word_lines: list[tuple[int, int, int, int]] = None,
    ) -> list[TemplateMatchResult]:
        """
        Find all possible templates locations above a score-threshold, provided a list of templates to search and an image.
        Resulting detections are not filtered by NMS and thus might overlap.Use :meth:`~:run` to perform the search with NMS.
        """
        ...

    def run(
        self,
        frames: list[np.ndarray],
        template_frames: list[np.ndarray],
        template_boxes: list[tuple[int, int, int, int]],
        template_labels: list[str],
        template_texts: list[str] = None,
        metadata: Optional[Union[dict, list]] = None,
        score_threshold: float = 0.90,
        scoring_strategy: str = "weighted",  # "weighted" or "average"
        max_overlap: float = 0.5,
        max_objects: int = 1,
        window_size: tuple[int, int] = (384, 128),  # h, w
        regions: list[tuple[int, int, int, int]] = None,
        downscale_factor: float = 1.0,
        batch_size: Optional[int] = None,
    ) -> list[TemplateMatchResult]:
        """
        Search each template in the images, and return the best `max_objects` locations which offer the best score and which do not overlap.

        :param metadata:
        :param frames: A list of images in which to perform the search, it should be the same depth and number of channels that of the templates.

        :param template_frames: A list of templates as numpy array to search in each image.
        :param template_boxes: A list of bounding boxes for each template. The length of this list should be the same as the length of the templates list.
        :param template_labels: A list of labels for each template. The length of this list should be the same as the length of the templates list.
        :param template_texts: A list of text for each template. The length of this list should be the same as the length of the templates list.
        :param metadata: A list of metadata for each frame. The length of this list should be the same as the length of the frames list.
        :param score_threshold: The minimum score to consider a match.
        :param scoring_strategy: The strategy to use for scoring the matches. It can be either "weighted" or "average".
        :param max_overlap: The maximum overlap to consider a match. This is the maximal value for the ratio of the Intersection Over Union (IoU) area between a pair of bounding boxes.
        :param max_objects: The maximum number of objects to return.
        :param window_size: The size of the window to use for the search in the format (width, height).
        :param regions: A list of regions of interest in the images in the format (x, y, width, height). If None, the whole image is considered.
        :param downscale_factor: The factor by which to downscale the images before performing the search. This is useful to speed up the search.
        :param batch_size: The batch size to use for the prediction.
        :return: A list of TemplateMatchResults
        """

        # assertions can be disabled via the the -O flag  (python -O)
        if not (0 <= score_threshold <= 1):
            raise ValueError("Score threshold should be between 0 and 1")
        if not (0 <= max_overlap <= 1):
            raise ValueError("Max overlap should be between 0 and 1")
        if not max_objects > 0:
            raise ValueError("Max object should be greater than 0")
        if downscale_factor > 1 or downscale_factor < 0:
            raise ValueError("Downscale factor should be between 0 and 1")
        if batch_size is not None and not batch_size > 0:
            raise ValueError("Batch size should be either None or greater than 0")
        if regions is None:
            regions = [(0, 0, image.shape[1], image.shape[0]) for image in frames]

        if len(frames) != len(regions):
            raise ValueError(
                "The length of the regions list should be the same as the length of the frames list."
            )

        results = []
        postprocess = self.setup_postprocess()
        # validate the template frames are the same size as the window size
        for k, (template_frame, template_box) in enumerate(
            zip(template_frames, template_boxes)
        ):
            assert template_frame.shape[0] == window_size[0]
            assert template_frame.shape[1] == window_size[1]

            if (
                template_frame.shape[0] != window_size[0]
                or template_frame.shape[1] != window_size[1]
            ):
                raise ValueError(
                    "Template frame size does not match window size, please resize the template frames to match the window size"
                )

            if downscale_factor != 1:
                template_frame = resize_image_progressive(
                    template_frame,
                    reduction_percent=1.0 - downscale_factor,
                    reductions=2,
                    return_intermediate_states=False,
                )

                template_frames[k] = template_frame
                template_box = [
                    template_box[0] * downscale_factor,
                    template_box[1] * downscale_factor,
                    template_box[2] * downscale_factor,
                    template_box[3] * downscale_factor,
                ]
                template_box = [int(x) for x in template_box]
                template_boxes[k] = template_box

        for frame_idx, (frame, region) in enumerate(zip(frames, regions)):
            self.logger.info(f"matching frame {frame_idx} region: {region}")
            assert frame.ndim == 3
            if downscale_factor != 1:
                frame = resize_image_progressive(
                    frame,
                    reduction_percent=1.0 - downscale_factor,
                    reductions=2,
                    return_intermediate_states=False,
                )
                # downscale the template boxes
                cv2.imwrite(
                    f"/tmp/dim/template_image_downscaled_{frame_idx}.png",
                    frame,
                )

            page_words = []
            page_boxes = []
            page_lines = []

            if metadata is not None:
                page_words, page_boxes, page_lines = get_words_and_boxes(
                    metadata, frame_idx, include_lines=True
                )

            # for profiling
            durations_in_seconds = dict()
            # currently only 1 batch supported
            num_batch = 1
            image = Image.fromarray(frame)

            if self.slicing_enabled:
                slice_height = window_size[0]
                slice_width = window_size[1]
                overlap_height_ratio = self.DEFAULT_OVERLAP_HEIGHT_RATIO
                overlap_width_ratio = self.DEFAULT_OVERLAP_WIDTH_RATIO
                output_file_name = "frame_"
            else:
                slice_height = frame.shape[0]
                slice_width = frame.shape[1]
                overlap_height_ratio = 0
                overlap_width_ratio = 0
                output_file_name = None

            # create slices from full image
            time_start = time.time()
            slice_image_result = slice_image(
                image=image,
                output_file_name=output_file_name,  # ADDED OUTPUT FILE NAME TO (OPTIONALLY) SAVE SLICES
                output_dir=None,  # "/tmp/dim/slices",  # ADDED INTERIM DIRECTORY TO (OPTIONALLY) SAVE SLICES
                slice_height=slice_height,
                slice_width=slice_width,
                overlap_height_ratio=overlap_height_ratio,
                overlap_width_ratio=overlap_width_ratio,
                auto_slice_resolution=False,
            )

            num_slices = len(slice_image_result)
            time_end = time.time() - time_start
            durations_in_seconds["slice"] = time_end

            image_list = []
            shift_amount_list = []

            for idx, slice_result in enumerate(slice_image_result):
                patch = slice_result["image"]
                starting_pixel = slice_result["starting_pixel"]
                image_list.append(patch)
                shift_amount_list.append(starting_pixel)

            result_bboxes = []
            result_labels = []
            result_scores = []
            result_snippets = []

            for idx, (patch, offset) in enumerate(zip(image_list, shift_amount_list)):
                prediction_time_start = time.time()
                offset_x, offset_y = offset
                predictions = self.predict(
                    patch,
                    template_frames,
                    template_boxes,
                    template_labels,
                    template_texts,
                    score_threshold,
                    scoring_strategy,
                    max_objects,
                    words=page_words,
                    word_boxes=page_boxes,
                    word_lines=page_lines,
                )

                prediction_time_end = time.time() - prediction_time_start
                durations_in_seconds["prediction"] = prediction_time_end
                self.logger.debug(
                    f"Slice-prediction performed in {durations_in_seconds['prediction']} seconds."
                )

                for prediction in predictions:
                    bbox = prediction.bbox
                    shifted_bbox = [
                        bbox[0] + offset_x,
                        bbox[1] + offset_y,
                        bbox[2],
                        bbox[3],
                    ]
                    snippet = patch[
                        bbox[1] : bbox[1] + bbox[3], bbox[0] : bbox[0] + bbox[2]
                    ]
                    result_snippets.append(snippet)
                    result_bboxes.append(shifted_bbox)
                    result_labels.append(prediction.label)
                    result_scores.append(prediction.score)

            result_bboxes, result_labels, result_scores = self.filter_scores(
                result_bboxes,
                result_labels,
                result_scores,
                result_snippets,
                score_threshold,
            )

            result_bboxes = [
                bbox
                for _, bbox in sorted(
                    zip(result_scores, result_bboxes),
                    key=lambda pair: pair[0],
                    reverse=True,
                )
            ]
            result_labels = [
                label
                for _, label in sorted(
                    zip(result_scores, result_labels),
                    key=lambda pair: pair[0],
                    reverse=True,
                )
            ]

            result_scores = sorted(result_scores, reverse=True)

            object_prediction_list: List[ObjectPrediction] = (
                self.to_object_prediction_list(
                    result_bboxes, result_labels, result_scores
                )
            )

            if postprocess is not None:
                object_prediction_list = postprocess(object_prediction_list)

            durations_in_seconds["postprocess"] = time.time() - time_start
            object_result_map = self.to_object_result_map(
                object_prediction_list, frame_idx
            )

            # flatten the object_result_map
            result_bboxes = []
            result_labels = []
            result_scores = []
            result_snippets = []
            idx = 0

            for label, predictions in object_result_map.items():
                for prediction in predictions:
                    snippet = frame[
                        prediction.bbox[1] : prediction.bbox[1] + prediction.bbox[3],
                        prediction.bbox[0] : prediction.bbox[0] + prediction.bbox[2],
                    ]
                    result_bboxes.append(prediction.bbox)
                    result_labels.append(prediction.label)
                    result_scores.append(prediction.score)
                    result_snippets.append(snippet)

                    # if we have downscale_factor we need to resize the prediction bbox
                    if downscale_factor != 1:
                        prediction.bbox = [
                            int(x / downscale_factor) for x in prediction.bbox
                        ]

                    results.append(
                        TemplateMatchResult(
                            bbox=prediction.bbox,
                            label=prediction.label,
                            score=prediction.score,
                            similarity=prediction.similarity,
                            frame_index=frame_idx,
                        )
                    )
                    # cv2.imwrite(f"/tmp/dim/snippet/snippet_{label}_{idx}.png", snippet)
                    idx += 1

            if len(frame.shape) == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)

            self.visualize_object_predictions(
                result_bboxes, result_labels, result_scores, frame, frame_idx
            )

            time_end = time.time() - time_start
            durations_in_seconds["prediction"] = time_end
            verbose = 2

            if verbose == 2:
                print(
                    "Slicing performed in",
                    durations_in_seconds["slice"],
                    "seconds.",
                )
                print(
                    "Prediction performed in",
                    durations_in_seconds["prediction"],
                    "seconds.",
                )
        torch_gc()
        return results

    def setup_postprocess(self):
        postprocess_type = "GREEDYNMM"
        postprocess_match_metric = "IOS"
        postprocess_match_threshold = 0.5
        postprocess_class_agnostic = False
        # init match postprocess instance
        if postprocess_type not in POSTPROCESS_NAME_TO_CLASS.keys():
            raise ValueError(
                f"postprocess_type should be one of {list(POSTPROCESS_NAME_TO_CLASS.keys())} but given as {postprocess_type}"
            )
        postprocess_constructor = POSTPROCESS_NAME_TO_CLASS[postprocess_type]
        postprocess = postprocess_constructor(
            match_threshold=postprocess_match_threshold,
            match_metric=postprocess_match_metric,
            class_agnostic=postprocess_class_agnostic,
        )
        return postprocess

    @staticmethod
    def visualize_object_predictions(
        bboxes, labels, scores, frame, index, border_only=True
    ) -> None:
        """
        Visualize the object predictions on the frame.
        :param bboxes:  bounding boxes to visualize
        :param labels:  labels to visualize
        :param scores:  scores to visualize
        :param frame_cp:  frame to draw the predictions on
        :param index:  index of the frame
        :param border_only:  whether to draw only the border of the bounding boxes
        :return:
        """
        frm = frame.copy()
        colors = {label: np.random.randint(0, 255, 3).tolist() for label in set(labels)}
        for bbox, label, score in zip(bboxes, labels, scores):
            if border_only:
                cv2.rectangle(
                    frm,
                    (bbox[0], bbox[1]),
                    (bbox[0] + bbox[2], bbox[1] + bbox[3]),
                    # (0, 255, 0),
                    colors[label],
                    2,
                )
            else:
                overlay = frm.copy()
                cv2.rectangle(
                    overlay,
                    (bbox[0], bbox[1]),
                    (bbox[0] + bbox[2], bbox[1] + bbox[3]),
                    colors[label],  # color of the overlay
                    -1,
                )
                alpha = 0.5
                frm = cv2.addWeighted(overlay, alpha, frm, 1 - alpha, 0)
            cv2.putText(
                frm,
                f"{score:.2f}",
                # (bbox[0], bbox[1] + bbox[3] // 2 + 5),
                (bbox[0], bbox[1] - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 255),
                1,
            )

        # create random id for the frame
        rid = np.random.randint(0, 1000)
        cv2.imwrite(f"/tmp/dim/results_frame_{index}-rid_{rid}.png", frm)

    def filter_scores(
        self, bboxes, labels, scores, snippets, score_threshold
    ) -> tuple[list, list, list]:
        """
        Filter out scores below the threshold.
        :param bboxes: bounding boxes
        :param labels: labels to filter
        :param scores:  scores to filter
        :param snippets: snippets to filter
        :param score_threshold:
        :return:
        """
        assert len(bboxes) == len(labels) == len(scores) == len(snippets)
        bboxes = [
            bbox for bbox, score in zip(bboxes, scores) if score > score_threshold
        ]

        labels = [
            label for label, score in zip(labels, scores) if score > score_threshold
        ]

        scores = [score for score in scores if score > score_threshold]
        return bboxes, labels, scores

    def to_object_prediction_list(
        self, bboxes, labels, scores
    ) -> List[ObjectPrediction]:
        """
        Convert the results to a list of ObjectPrediction.
        :param bboxes:  bounding boxes to convert in the format (x, y, width, height)
        :param labels:  labels to convert
        :param scores: scores to convert in range [0, 1]
        :return:  a list of ObjectPrediction
        """

        label_id = {label: idx for idx, label in enumerate(set(labels))}
        object_prediction_list: List[ObjectPrediction] = []

        for bbox, label, score in zip(bboxes, labels, scores):
            # convert to x, y, x2, y2
            bbox = [bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3]]

            object_prediction = ObjectPrediction(
                category_name=label,
                category_id=label_id[label],
                bbox=bbox,
                score=score,
                shift_amount=[0, 0],
            )
            object_prediction_list.append(object_prediction)

        return object_prediction_list

    def to_object_result_map(
        self, object_prediction_list: List[ObjectPrediction], frame_idx: int
    ):

        object_result_map = {}
        for object_prediction in object_prediction_list:
            label = object_prediction.category.name
            if label not in object_result_map:
                object_result_map[label] = []

            bbox: BoundingBox = object_prediction.bbox
            bbox = bbox.to_xywh()  # convert to x, y, width, height

            score: PredictionScore = object_prediction.score
            score = score.value

            object_result_map[label].append(
                TemplateMatchResult(
                    bbox=bbox,
                    label=label,
                    score=score,
                    similarity=score,
                    frame_index=frame_idx,
                )
            )
        return object_result_map

    def viz_patches(self, patches, filename: str) -> None:
        from matplotlib import pyplot as plt

        plt.figure(figsize=(9, 9))
        square_x = patches.shape[1]
        square_y = patches.shape[0]

        ix = 1
        for i in range(square_y):
            for j in range(square_x):
                # specify subplot and turn of axis
                ax = plt.subplot(square_y, square_x, ix)
                ax.set_xticks([])
                ax.set_yticks([])
                # plot
                plt.imshow(patches[i, j, :, :], cmap="gray")
                ix += 1
        # show the figure
        # plt.show()
        plt.savefig(filename)
        plt.close()

    @staticmethod
    def extract_windows(
        image: np.ndarray,
        template_bboxes: list[Union[tuple[int, int, int, int], list[int]]],
        window_size: tuple[int, int],
        allow_padding: bool = False,
    ) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
        """
        Extract windows snippet from the input image centered around the template bbox and resize it to the desired size.

        :param image: input image in the format (h, w, c) to extract the windows from
        :param template_bboxes: list of bboxes in the format (x, y, w, h)
        :param window_size: (h, w) size of the window to extract
        :param allow_padding:  whether to allow padding the image to the desired size if it is smaller than the window size
        :return: list of windows and list of bboxes
        """

        windows = []
        bboxes = []

        img_h, img_w = image.shape[:2]
        desired_h, desired_w = window_size

        if img_h < window_size[0] or img_w < window_size[1]:
            if not allow_padding:
                raise ValueError(
                    f"Image size should be greater than the window size, expected {window_size} but got {image.shape[:2]}"
                )

            image = cv2.copyMakeBorder(
                image,
                0,
                max(0, window_size[0] - img_h),
                0,
                max(0, window_size[1] - img_w),
                cv2.BORDER_CONSTANT,
                value=(255, 255, 255),
            )
            img_h, img_w = image.shape[:2]

        for box in template_bboxes:
            x_, y_, w_, h_ = box  # x, y, w, h

            center_x = x_ + w_ // 2
            center_y = y_ + h_ // 2

            x = max(0, center_x - desired_w // 2)
            y = max(0, center_y - desired_h // 2)
            w = desired_w
            h = desired_h

            if x + w > img_w:
                x = img_w - w
            if y + h > img_h:
                y = img_h - h

            window = image[y : y + h, x : x + w, :]
            coord = center_x - x - w_ // 2, center_y - y - h_ // 2, w_, h_
            if window.shape[0] != window_size[0] or window.shape[1] != window_size[1]:
                raise Exception(
                    "Template frame size does not match window size, please resize the template frames to match the window size"
                )
            windows.append(window)
            bboxes.append(coord)
        return windows, bboxes
