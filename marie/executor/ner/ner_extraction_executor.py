import os
import cv2
import torch
from builtins import print

from docarray import DocumentArray
from torch.backends import cudnn
import torch.nn.functional as nn

from marie import Executor, requests, __model_path__
from marie.executor.ner.utils import (
    normalize_bbox,
    unnormalize_box,
    iob_to_label,
    get_font,
    get_random_color,
    draw_box,
    visualize_icr,
    visualize_prediction,
    visualize_extract_kv,
)

from marie.logging.logger import MarieLogger
from marie.utils.utils import ensure_exists
from marie.utils.overlap import find_overlap_horizontal
from marie.utils.overlap import merge_bboxes_as_block

from PIL import Image, ImageDraw, ImageFont
import logging
from typing import Optional, List, Any, Tuple, Dict

import numpy as np

from PIL import Image
from transformers import AutoModelForTokenClassification, AutoProcessor

from transformers import (
    LayoutLMv3Processor,
    LayoutLMv3FeatureExtractor,
    LayoutLMv3ForTokenClassification,
    LayoutLMv3TokenizerFast,
)


from transformers.utils import check_min_version

# Will error if the minimal version of Transformers is not installed. Remove at your own risks.
from marie.boxes.line_processor import find_line_number
from marie.executor import TextExtractionExecutor
from marie.executor.text_extraction_executor import CoordinateFormat
from marie.utils.docs import (
    docs_from_file,
    array_from_docs,
    docs_from_image,
    load_image,
    __convert_frames,
)

from marie.utils.image_utils import viewImage, read_image, hash_file
from marie.utils.json import store_json_object, load_json_file
from pathlib import Path

# Calling this from here prevents : "AttributeError: module 'detectron2' has no attribute 'config'"
from detectron2.config import get_cfg

check_min_version("4.5.0")
logger = logging.getLogger(__name__)


def get_marie_home():
    return os.path.join(str(Path.home()), ".marie")


def obtain_ocr(src_image: str, text_executor: TextExtractionExecutor):
    """
    Obtain OCR words
    """
    docs = docs_from_file(src_image)
    frames = array_from_docs(docs)
    kwa = {"payload": {"output": "json", "mode": "sparse", "format": "xyxy"}}
    results = text_executor.extract(docs, **kwa)

    return results, frames


def create_processor():
    """prepare for the model"""
    # Method:2 Create Layout processor with custom future extractor
    # Max model size is 512, so we will need to handle any documents larger than that
    feature_extractor = LayoutLMv3FeatureExtractor(apply_ocr=False)
    tokenizer = LayoutLMv3TokenizerFast.from_pretrained(
        "microsoft/layoutlmv3-large"
        # only_label_first_subword = True
    )
    processor = LayoutLMv3Processor(
        feature_extractor=feature_extractor, tokenizer=tokenizer
    )

    return processor


def load_model(model_dir: str, fp16: bool, device):
    """
    Create token classification model
    """
    print(f"TokenClassification dir : {model_dir}")
    labels, _, _ = get_label_info()
    model = AutoModelForTokenClassification.from_pretrained(
        model_dir, num_labels=len(labels)
    )

    model.to(device)
    return model


def get_label_info():
    labels = [
        "O",
        "B-MEMBER_NAME",
        "I-MEMBER_NAME",
        "B-MEMBER_NUMBER",
        "I-MEMBER_NUMBER",
        "B-PAN",
        "I-PAN",
        "B-PATIENT_NAME",
        "I-PATIENT_NAME",
        "B-DOS",
        "I-DOS",
        "B-DOS_ANSWER",
        "I-DOS_ANSWER",
        "B-PATIENT_NAME_ANSWER",
        "I-PATIENT_NAME_ANSWER",
        "B-MEMBER_NAME_ANSWER",
        "I-MEMBER_NAME_ANSWER",
        "B-MEMBER_NUMBER_ANSWER",
        "I-MEMBER_NUMBER_ANSWER",
        "B-PAN_ANSWER",
        "I-PAN_ANSWER",
        "B-ADDRESS",
        "I-ADDRESS",
        "B-GREETING",
        "I-GREETING",
        "B-HEADER",
        "I-HEADER",
        "B-LETTER_DATE",
        "I-LETTER_DATE",
        "B-PARAGRAPH",
        "I-PARAGRAPH",
        "B-QUESTION",
        "I-QUESTION",
        "B-ANSWER",
        "I-ANSWER",
        "B-DOCUMENT_CONTROL",
        "I-DOCUMENT_CONTROL",
        "B-PHONE",
        "I-PHONE",
        "B-URL",
        "I-URL",
        "B-CLAIM_NUMBER",
        "I-CLAIM_NUMBER",
        "B-CLAIM_NUMBER_ANSWER",
        "I-CLAIM_NUMBER_ANSWER",
        "B-BIRTHDATE",
        "I-BIRTHDATE",
        "B-BIRTHDATE_ANSWER",
        "I-BIRTHDATE_ANSWER",
        "B-BILLED_AMT",
        "I-BILLED_AMT",
        "B-BILLED_AMT_ANSWER",
        "I-BILLED_AMT_ANSWER",
        "B-PAID_AMT",
        "I-PAID_AMT",
        "B-PAID_AMT_ANSWER",
        "I-PAID_AMT_ANSWER",
        "B-CHECK_AMT",
        "I-CHECK_AMT",
        "B-CHECK_AMT_ANSWER",
        "I-CHECK_AMT_ANSWER",
        "B-CHECK_NUMBER",
        "I-CHECK_NUMBER",
        "B-CHECK_NUMBER_ANSWER",
        "I-CHECK_NUMBER_ANSWER",
    ]

    logger.info(f"Labels : {labels}")

    id2label = {v: k for v, k in enumerate(labels)}
    label2id = {k: v for v, k in enumerate(labels)}

    return labels, id2label, label2id


def get_label_colors():
    return {
        "pan": "blue",
        "pan_answer": "green",
        "dos": "orange",
        "dos_answer": "violet",
        "member": "blue",
        "member_answer": "green",
        "member_number": "blue",
        "member_number_answer": "green",
        "member_name": "blue",
        "member_name_answer": "green",
        "patient_name": "blue",
        "patient_name_answer": "green",
        "paragraph": "purple",
        "greeting": "blue",
        "address": "orange",
        "question": "blue",
        "answer": "aqua",
        "document_control": "grey",
        "header": "brown",
        "letter_date": "deeppink",
        "url": "darkorange",
        "phone": "darkmagenta",
        "other": "red",
        "claim_number": "darkmagenta",
        "claim_number_answer": "green",
        "birthdate": "green",
        "birthdate_answer": "red",
        "billed_amt": "green",
        "billed_amt_answer": "orange",
        "paid_amt": "green",
        "paid_amt_answer": "blue",
        "check_amt": "orange",
        "check_amt_answer": "darkmagenta",
        "check_number": "orange",
        "check_number_answer": "blue",
    }


def get_ocr_line_bbox(bbox, frame, text_executor):
    box = np.array(bbox).astype(np.int32)
    x, y, w, h = box
    img = frame
    if isinstance(frame, Image.Image):
        img = cv2.cvtColor(np.array(frame), cv2.COLOR_RGB2BGR)

    snippet = img[y : y + h, x : x + w :]
    docs = docs_from_image(snippet)
    kwa = {"payload": {"output": "json", "mode": "raw_line"}}
    results = text_executor.extract(docs, **kwa)

    if len(results) > 0:
        words = results[0]["words"]
        if len(words) > 0:
            word = words[0]
            return word["text"], word["confidence"]
    return "", 0.0


def _filter(
    values: List[Any], probabilities: List[float], threshold: float
) -> List[Any]:
    return [value for probs, value in zip(probabilities, values) if probs >= threshold]


def infer(
    file_hash: str,
    frame_idx: int,
    model: Any,
    processor: Any,
    image: Any,
    labels: List[str],
    threshold: float,
    words: List[Any],
    boxes: List[Any],
    device: str,
) -> Tuple[List, List, List]:
    logger.info(f"Performing inference")

    id2label = {v: k for v, k in enumerate(labels)}

    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    logger.info(
        f"Tokenizer parallelism: {os.environ.get('TOKENIZERS_PARALLELISM', 'true')}"
    )

    # image = # Image.open(eg["path"]).convert("RGB")
    width, height = image.size
    # https://huggingface.co/docs/transformers/model_doc/layoutlmv2#transformers.LayoutLMv2ForTokenClassification
    # Encode the image
    word_labels = []
    for i in range(0, len(boxes)):
        word_labels.append(1)

    encoding = processor(
        # fmt: off
        image,
        words,
        boxes=boxes,
        truncation=True,
        return_offsets_mapping=True,
        padding="max_length",
        return_tensors="pt"
        # fmt: on
    )
    offset_mapping = encoding.pop("offset_mapping")

    # Debug tensor info
    if False:
        # img_tensor = encoded_inputs["image"] # v2
        img_tensor = encoding["pixel_values"]  # v3
        img = Image.fromarray(
            (img_tensor[0].cpu()).numpy().astype(np.uint8).transpose(1, 2, 0)
        )
        img.save(f"/tmp/tensors/tensor_{file_hash}_{frame_idx}.png")

    for ek, ev in encoding.items():
        encoding[ek] = ev.to(device)

    # Perform forward pass
    with torch.no_grad():
        outputs = model(**encoding)
        # Get the predictions and probabilities
        probs = nn.softmax(outputs.logits.squeeze(), dim=1).max(dim=1).values.tolist()
        _predictions = outputs.logits.argmax(-1).squeeze().tolist()
        _token_boxes = encoding.bbox.squeeze().tolist()
        normalized_logits = outputs.logits.softmax(dim=-1).squeeze().tolist()

    # TODO : Filer the results
    # Filter the predictions and bounding boxes based on a threshold
    # predictions = _filter(_predictions, probs, threshold)
    # token_boxes = _filter(_token_boxes, probs, threshold)
    predictions = _predictions
    token_boxes = _token_boxes

    # Only keep non-subword predictions
    is_subword = np.array(offset_mapping.squeeze().tolist())[:, 0] != 0
    true_predictions = [
        id2label[pred] for idx, pred in enumerate(predictions) if not is_subword[idx]
    ]
    true_boxes = [
        unnormalize_box(box, width, height)
        for idx, box in enumerate(token_boxes)
        if not is_subword[idx]
    ]

    true_scores = [
        round(normalized_logits[idx][val], 6)
        for idx, val in enumerate(predictions)
        if not is_subword[idx]
    ]

    all_predictions = []
    all_boxes = []
    all_scores = []

    all_predictions.append(true_predictions)
    all_boxes.append(true_boxes)
    all_scores.append(true_scores)

    assert len(true_predictions) == len(true_boxes) == len(true_scores)
    return all_predictions, all_boxes, all_scores


class NerExtractionExecutor(Executor):
    """
    Executor for extracting text.
    Text extraction can either be executed out over the entire image or over selected regions of interests (ROIs)
    aka bounding boxes.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.show_error = True  # show prediction errors
        self.logger = MarieLogger(
            getattr(self.metas, "name", self.__class__.__name__)
        ).logger

        self.logger.info("NER Extraction Executor")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # sometimes we have CUDA/GPU support but want to only use CPU
        use_cuda = torch.cuda.is_available()
        if os.environ.get("MARIE_DISABLE_CUDA"):
            use_cuda = False
            self.device = "cpu"

        if use_cuda:
            cudnn.benchmark = False
            cudnn.deterministic = False

        ensure_exists("/tmp/tensors")
        ensure_exists("/tmp/tensors/json")

        models_dir = os.path.join(__model_path__, "ner-rms-corr", "checkpoint-best")

        models_dir = (
            "/mnt/data/models/layoutlmv3-large-finetuned-splitlayout/checkpoint-24500"
        )

        self.model = load_model(models_dir, True, self.device)
        self.processor = create_processor()
        self.text_executor = TextExtractionExecutor()

    def info(self, **kwargs):
        logger.info(f"Self : {self}")
        return {"index": "ner-complete"}

    def aggregate_results(
        self, src_image: str, text_executor: Optional[TextExtractionExecutor] = None
    ):
        if not os.path.exists(src_image):
            raise FileNotFoundError(src_image)

        # Obtain OCR results
        file_hash = hash_file(src_image)
        root_dir = get_marie_home()
        ocr_json_path = os.path.join(root_dir, "ocr", f"{file_hash}.json")
        annotation_json_path = os.path.join(root_dir, "annotation", f"{file_hash}.json")

        print(f"OCR file  : {ocr_json_path}")
        print(f"NER file  : {annotation_json_path}")

        if not os.path.exists(ocr_json_path):
            raise FileNotFoundError(ocr_json_path)

        if not os.path.exists(ocr_json_path):
            raise FileNotFoundError(annotation_json_path)

        loaded, frames = load_image(src_image, img_format="pil")
        if not loaded:
            raise Exception(f"Unable to load image file: {src_image}")

        ocr_results = load_json_file(ocr_json_path)
        annotation_results = load_json_file(annotation_json_path)
        assert len(annotation_results) == len(ocr_results) == len(frames)

        # need to normalize all data from XYXY to XYWH as the NER process required XYXY and assets were saved XYXY format
        logger.info("Changing coordinate format from xyxy->xyhw")
        for data in ocr_results:
            for word in data["words"]:
                word["box"] = CoordinateFormat.convert(
                    word["box"], CoordinateFormat.XYXY, CoordinateFormat.XYWH
                )

        for data in annotation_results:
            for i, box in enumerate(data["boxes"]):
                box = CoordinateFormat.convert(
                    box, CoordinateFormat.XYXY, CoordinateFormat.XYWH
                )
                data["boxes"][i] = box

        aggregated_kv = []
        aggregated_meta = []

        expected_keys = [
            "PAN",
            "PAN_ANSWER",
            "PATIENT_NAME",
            "PATIENT_NAME_ANSWER",
            "DOS",
            "DOS_ANSWER",
            "MEMBER_NAME",
            "MEMBER_NAME_ANSWER",
            "MEMBER_NUMBER",
            "MEMBER_NUMBER_ANSWER",
            "QUESTION",
            "ANSWER",  # Only collect ANSWERs for now
            "LETTER_DATE",
            "PHONE",
            "URL",
            "CLAIM_NUMBER",
            "CLAIM_NUMBER_ANSWER",
            "BIRTHDATE",
            "BIRTHDATE_ANSWER",
            "BILLED_AMT",
            "BILLED_AMT_ANSWER",
            "PAID_AMT",
            "PAID_AMT_ANSWER",
            # "ADDRESS",
        ]

        # expected_keys = ["PAN", "PAN_ANSWER"]

        # expected KV pairs
        expected_pair = [
            ["PAN", ["PAN_ANSWER", "ANSWER"]],
            ["CLAIM_NUMBER", ["CLAIM_NUMBER_ANSWER", "ANSWER"]],
            ["BIRTHDATE", ["BIRTHDATE_ANSWER", "ANSWER"]],
            ["PATIENT_NAME", ["PATIENT_NAME_ANSWER", "ANSWER"]],
            ["DOS", ["DOS_ANSWER", "ANSWER"]],
            ["MEMBER_NAME", ["MEMBER_NAME_ANSWER", "ANSWER"]],
            ["MEMBER_NUMBER", ["MEMBER_NUMBER_ANSWER", "ANSWER"]],
            ["BILLED_AMT", ["BILLED_AMT_ANSWER"]],
            ["PAID_AMT", ["PAID_AMT_ANSWER"]],
            ["QUESTION", ["ANSWER"]],
        ]

        for i, (ocr, ann, frame) in enumerate(
            zip(ocr_results, annotation_results, frames)
        ):
            print(f"Processing page # {i}")
            logger.info(f"Processing page # {i}")
            # lines and boxes are already in the right reading order TOP->BOTTOM, LEFT-TO-RIGHT so no need to sort
            lines_bboxes = np.array(ocr["meta"]["lines_bboxes"])
            true_predictions = ann["predictions"]
            true_boxes = ann["boxes"]
            true_scores = ann["scores"]

            viz_img = frame.copy()
            draw = ImageDraw.Draw(viz_img, "RGBA")
            font = get_font(14)
            # aggregate boxes into their lines
            groups = {}
            for j, (prediction, pred_box, pred_score) in enumerate(
                zip(true_predictions, true_boxes, true_scores)
            ):
                # discard 'O' other
                label = prediction[2:]
                if not label:
                    continue
                # two labels that need to be removed [0.0, 0.0, 0.0, 0.0]  [2578.0, 3 3292.0, 0.0, 0.0]
                if (
                    pred_box == [0.0, 0.0, 0.0, 0.0]
                    or pred_box[2] == 0
                    or pred_box[3] == 0
                ):
                    continue

                line_number = find_line_number(lines_bboxes, pred_box)
                if line_number not in groups:
                    groups[line_number] = []
                groups[line_number].append(j)

            # aggregate boxes into key/value pairs via simple state machine for each line
            aggregated_keys = {}

            for line_idx, line_box in enumerate(lines_bboxes):
                if line_idx not in groups:
                    logger.debug(
                        f"Line does not have any groups : {line_idx} : {line_box}"
                    )
                    continue

                prediction_indexes = np.array(groups[line_idx])
                line_aggregator = []
                color_map = {"ADDRESS": get_random_color()}

                for key in expected_keys:
                    aggregated = []
                    skip_to = -1
                    for m in range(0, len(prediction_indexes)):
                        if skip_to != -1 and m <= skip_to:
                            continue
                        pred_idx = prediction_indexes[m]
                        prediction = true_predictions[pred_idx]
                        label = prediction[2:]
                        aggregator = []

                        if label == key:
                            for n in range(m, len(prediction_indexes)):
                                pred_idx = prediction_indexes[n]
                                prediction = true_predictions[pred_idx]
                                label = prediction[2:]
                                if label != key:
                                    break
                                aggregator.append(pred_idx)
                                skip_to = n

                        if len(aggregator) > 0:
                            aggregated.append(aggregator)

                    if len(aggregated) > 0:
                        line_aggregator.append({"key": key, "groups": aggregated})

                true_predictions = np.array(true_predictions)
                true_boxes = np.array(true_boxes)
                true_scores = np.array(true_scores)

                for line_agg in line_aggregator:
                    field = line_agg["key"]
                    group_indexes = line_agg["groups"]

                    for group_index in group_indexes:
                        bboxes = true_boxes[group_index]
                        scores = true_scores[group_index]
                        group_score = round(np.average(scores), 6)
                        # create a bounding box around our blocks which could be possibly overlapping or being split
                        group_bbox = merge_bboxes_as_block(bboxes)

                        key_result = {
                            "line": line_idx,
                            "key": field,
                            "bbox": group_bbox,
                            "score": group_score,
                        }

                        if line_idx not in aggregated_keys:
                            aggregated_keys[line_idx] = []
                        aggregated_keys[line_idx].append(key_result)

                        color = (
                            color_map[field]
                            if field in color_map
                            else get_random_color()
                        )

                        draw_box(
                            draw,
                            group_bbox,
                            None,
                            color,
                            font,
                        )

            # check if we have possible overlaps when there is a mislabeled token, this could be a flag
            # B-PAN I-PAN I-PAN B-PAN-ANS I-PAN

            for key in expected_keys:
                for ag_key in aggregated_keys.keys():
                    row_items = aggregated_keys[ag_key]
                    bboxes = [row["bbox"] for row in row_items if row["key"] == key]
                    visited = [False for _ in range(0, len(bboxes))]
                    to_merge = {}

                    for idx in range(0, len(bboxes)):
                        if visited[idx]:
                            continue
                        visited[idx] = True
                        box = bboxes[idx]
                        overlaps, indexes, scores = find_overlap_horizontal(box, bboxes)
                        to_merge[ag_key] = [idx]

                        for _, overlap_idx in zip(overlaps, indexes):
                            visited[overlap_idx] = True
                            to_merge[ag_key].append(overlap_idx)

                    for _k, idxs in to_merge.items():
                        items = aggregated_keys[_k]
                        items = np.array(items)
                        # there is nothing to merge, except the original block
                        if len(idxs) == 1:
                            continue

                        idxs = np.array(idxs)
                        picks = items[idxs]
                        remaining = np.delete(items, idxs)

                        score_avg = round(
                            np.average([item["score"] for item in picks]), 6
                        )
                        block = merge_bboxes_as_block([item["bbox"] for item in picks])

                        new_item = picks[0]
                        new_item["score"] = score_avg
                        new_item["bbox"] = block

                        aggregated_keys[_k] = np.concatenate(([new_item], remaining))

            # expected fields groups that indicate that the field could have been present but there was not associated
            possible_fields = {
                "PAN": ["PAN", "PAN_ANSWER"],
                "PATIENT_NAME": ["PATIENT_NAME", "PATIENT_NAME_ANSWER"],
                "DOS": ["DOS", "DOS_ANSWER"],
                "MEMBER_NAME": ["MEMBER_NAME", "MEMBER_NAME_ANSWER"],
                "MEMBER_NUMBER": ["MEMBER_NUMBER", "MEMBER_NUMBER_ANSWER"],
                "CLAIM_NUMBER": ["CLAIM_NUMBER", "CLAIM_NUMBER_ANSWER"],
                "BIRTHDATE": ["BIRTHDATE", "BIRTHDATE_ANSWER"],
                "BILLED_AMT": ["BILLED_AMT", "BILLED_AMT_ANSWER"],
                "PAID_AMT": ["PAID_AMT", "PAID_AMT_ANSWER"],
            }

            print(">>>>>>>>>>>")
            possible_field_meta = {}

            for field in possible_fields.keys():
                fields = possible_fields[field]
                possible_field_meta[field] = {"page": i, "found": False, "fields": []}

                for k in aggregated_keys.keys():
                    ner_keys = aggregated_keys[k]
                    for ner_key in ner_keys:
                        key = ner_key["key"]
                        if key in fields:
                            print(f"found : {field} > {key}")
                            possible_field_meta[field]["found"] = True
                            possible_field_meta[field]["fields"].append(key)

            print(possible_field_meta)
            aggregated_meta.append({"page": i, "fields": possible_field_meta})

            for pair in expected_pair:
                expected_question = pair[0]
                expected_answer = pair[1]

                for k in aggregated_keys.keys():
                    ner_keys = aggregated_keys[k]

                    found_question = None
                    found_answer = None

                    for ner_key in ner_keys:
                        key = ner_key["key"]
                        if expected_question == key:
                            found_question = ner_key
                            continue
                        # find the first match
                        if found_question is not None and found_answer is None:
                            # find the first match
                            for exp_key in expected_answer:
                                if key in exp_key:
                                    found_answer = ner_key
                                    break

                            if found_answer is not None:
                                bbox_q = found_question["bbox"]
                                bbox_a = found_answer["bbox"]

                                if bbox_a[0] < bbox_q[0]:
                                    logger.warning(
                                        "Answer is not on the right of question"
                                    )
                                    continue

                                category = found_question["key"]
                                kv_result = {
                                    "page": i,
                                    "category": category,
                                    "value": {
                                        "question": found_question,
                                        "answer": found_answer,
                                    },
                                }

                                aggregated_kv.append(kv_result)

            viz_img.save(f"/tmp/tensors/extract_{file_hash}_{i}.png")

        # Decorate our answers with proper TEXT
        kv_indexed = {}

        for agg_result in aggregated_kv:
            page_index = int(agg_result["page"])
            frame = frames[page_index]
            question = agg_result["value"]["question"]
            answer = agg_result["value"]["answer"]

            w1, c1 = get_ocr_line_bbox(question["bbox"], frame, text_executor)
            w2, c2 = get_ocr_line_bbox(answer["bbox"], frame, text_executor)

            question["text"] = {"text": w1, "confidence": c1}
            answer["text"] = {"text": w2, "confidence": c2}

            if page_index not in kv_indexed:
                kv_indexed[page_index] = []

            kv_indexed[page_index].append(agg_result)

        # visualize results per page
        if True:
            for k in range(0, len(frames)):
                output_filename = f"/tmp/tensors/kv_{file_hash}_{k}.png"
                items = [row for row in aggregated_kv if int(row["page"]) == k]
                visualize_extract_kv(output_filename, frames[k], items)

        logger.info(f"aggregated_kv : {aggregated_kv}")
        results = {"meta": aggregated_meta, "kv": aggregated_kv}

        # return aggregated_kv
        return results

    def main_image(
        self,
        src_image: str,
        model,
        device,
        text_executor: Optional[TextExtractionExecutor] = None,
    ):
        if not os.path.exists(src_image):
            print(f"File not found : {src_image}")
            return
        # Obtain OCR results
        file_hash = hash_file(src_image)
        root_dir = get_marie_home()

        ensure_exists(os.path.join(root_dir, "ocr"))
        ensure_exists(os.path.join(root_dir, "annotation"))

        ocr_json_path = os.path.join(root_dir, "ocr", f"{file_hash}.json")
        annotation_json_path = os.path.join(root_dir, "annotation", f"{file_hash}.json")

        print(f"Root      : {root_dir}")
        print(f"SrcImg    : {src_image}")
        print(f"Hash      : {file_hash}")
        print(f"OCR file  : {ocr_json_path}")
        print(f"NER file  : {annotation_json_path}")

        if not os.path.exists(ocr_json_path) and text_executor is None:
            raise Exception(f"OCR File not found : {ocr_json_path}")

        loaded, frames = load_image(src_image, img_format="pil")
        if not loaded:
            raise Exception(f"Unable to load image file: {src_image}")

        if not os.path.exists(ocr_json_path):
            results, frames = obtain_ocr(src_image, text_executor)
            # convert CV frames to PIL frame
            frames = __convert_frames(frames, img_format="pil")
            store_json_object(results, ocr_json_path)

        results = load_json_file(ocr_json_path)
        visualize_icr(frames, results, file_hash)

        assert len(results) == len(frames)
        annotations = []
        labels, id2label, label2id = get_label_info()

        for k, (result, image) in enumerate(zip(results, frames)):
            if not isinstance(image, Image.Image):
                raise "Frame should have been an PIL.Image instance"

            width = image.size[0]
            height = image.size[1]
            words = []
            boxes = []

            for i, word in enumerate(result["words"]):
                box_norm = normalize_bbox(word["box"], (width, height))
                words.append(word["text"].lower())
                boxes.append(box_norm)

                # This is to prevent following error
                # The expanded size of the tensor (516) must match the existing size (512) at non-singleton dimension 1.
                # print(len(boxes))
                if len(boxes) == 512:
                    print("Clipping MAX boxes at 512")
                    break

            assert len(words) == len(boxes)

            (all_predictions, all_boxes, all_scores) = infer(
                file_hash,
                k,
                self.model,
                self.processor,
                image,
                labels,
                0.1,
                words,
                boxes,
                self.device,
            )

            true_predictions = all_predictions[0]
            true_boxes = all_boxes[0]
            true_scores = all_scores[0]

            # show detail scores
            if False:
                for i, val in enumerate(predictions):
                    tp = true_predictions[i]
                    score = normalized_logits[i][val]
                    print(f" >> {tp} : {score}")

            annotation = {
                "meta": {"imageSize": {"width": width, "height": height}, "page": k},
                "predictions": true_predictions,
                "boxes": true_boxes,
                "scores": true_scores,
            }

            output_filename = f"/tmp/tensors/prediction_{file_hash}_{k}.png"
            visualize_prediction(
                output_filename,
                image,
                true_predictions,
                true_boxes,
                true_scores,
                label2color=get_label_colors(),
            )

            annotations.append(annotation)
        store_json_object(annotations, annotation_json_path)
        return annotations

    # @requests()
    def extract(self, docs: Optional[DocumentArray] = None, **kwargs):
        """
        Args:
            docs : Documents to process, they will be none for now
        """

        queue_id: str = kwargs.get("queue_id", "0000-0000-0000-0000")
        checksum: str = kwargs.get("checksum", "0000-0000-0000-0000")
        image_src: str = kwargs.get("img_path", None)

        for key, value in kwargs.items():
            print("The value of {} is {}".format(key, value))

        self.main_image(image_src, self.model, self.device, self.text_executor)
        ner_results = self.aggregate_results(image_src, self.text_executor)

        return ner_results
