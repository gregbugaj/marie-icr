import argparse
import concurrent.futures
import distutils.util
import glob
import hashlib
import io
import json
import logging
import multiprocessing as mp
import os
import random
import shutil
import string
import sys
import time
import uuid
from concurrent.futures.thread import ThreadPoolExecutor
from functools import lru_cache
from multiprocessing import Pool
# import rstr
import cv2
import numpy as np
# from faker import Faker
# from faker.providers import BaseProvider
from PIL import Image, ImageDraw, ImageFont

from marie.boxes import BoxProcessorUlimDit
from marie.boxes.box_processor import PSMode
from marie.boxes.craft_box_processor import BoxProcessorCraft
from marie.boxes.line_processor import find_line_number
from marie.document.trocr_icr_processor import TrOcrIcrProcessor
from marie.numpyencoder import NumpyEncoder
from marie.timer import Timer
from marie.utils.utils import ensure_exists

# FUNSD format can be found here
# https://guillaumejaume.github.io/FUNSD/description/

logger = logging.getLogger(__name__)
_tmp_path = "/tmp/marie"
# setup data aug


def from_json_file(filename):
    with io.open(filename, "r", encoding="utf-8") as json_file:
        data = json.load(json_file)
        return data


def __scale_height(img, target_size, method=Image.LANCZOS):
    ow, oh = img.size
    scale = oh / target_size
    w = ow / scale
    h = target_size  # int(max(oh / scale, crop_size))
    resized = img.resize((int(w), int(h)), method)
    return resized, resized.size


def load_image(image_path):
    if not os.path.exists(image_path):
        raise FileNotFoundError(image_path)

    image = cv2.imread(image_path)
    h, w = image.shape[0], image.shape[1]
    return image, (w, h)


def __convert_coco_to_funsd(
    src_dir: str,
    output_path: str,
    annotations_filename: str,
    config: object,
    strip_file_name_path: bool,
) -> None:
    """
    Convert CVAT annotated COCO dataset into FUNSD compatible format for finetuning models.
    """
    print("******* Conversion info ***********")
    print(f"src_dir     : {src_dir}")
    print(f"output_path : {output_path}")
    print(f"annotations : {annotations_filename}")
    print(f"strip_file_name_path : {strip_file_name_path}")

    data = from_json_file(annotations_filename)
    categories = data["categories"]
    images = data["images"]
    annotations = data["annotations"]
    images_by_id = {}

    for img in images:
        if strip_file_name_path:
            file_name = img["file_name"]
            img["file_name"] = file_name.split("/")[-1]
        images_by_id[int(img["id"])] = img

    cat_id_name = {}
    cat_name_id = {}

    for category in categories:
        cat_id_name[category["id"]] = category["name"]
        cat_name_id[category["name"]] = category["id"]

    ano_groups = {}
    # Group annotations by image_id as their key
    for ano in annotations:
        if ano["image_id"] not in ano_groups:
            ano_groups[ano["image_id"]] = []
        ano_groups[ano["image_id"]].append(ano)

    errors = []

    for group_id in ano_groups:
        grouping = ano_groups[group_id]

        # start conversion
        img_data = images_by_id[group_id]
        file_name = img_data["file_name"]
        filename = file_name.split("/")[-1].split(".")[0]
        src_img_path = os.path.join(src_dir, "images", file_name)
        src_img, size = load_image(src_img_path)

        form_dict = {"form": []}

        for ano in grouping:
            category_id = ano["category_id"]
            # Convert form XYWH -> xmin,ymin,xmax,ymax
            bbox = [int(x) for x in ano["bbox"]]
            bbox = [bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3]]
            category_name = cat_id_name[category_id]
            label = category_name

            gen_id = random.randint(0, 10000000)
            item = {
                "id": gen_id,
                "text": "POPULATE_VIA_ICR",
                "box": bbox,
                "label": label,
                "words": [
                    {"text": "POPULATE_VIA_ICR_WORD", "box": [0, 0, 0, 0]},
                ],
            }

            form_dict["form"].append(item)

        os.makedirs(os.path.join(output_path, "annotations_tmp"), exist_ok=True)
        os.makedirs(os.path.join(output_path, "images"), exist_ok=True)

        json_path = os.path.join(output_path, "annotations_tmp", f"{filename}.json")
        dst_img_path = os.path.join(output_path, "images", f"{filename}.png")

        if True:
            with open(json_path, "w") as json_file:
                json.dump(form_dict, json_file, indent=4)

            shutil.copyfile(src_img_path, dst_img_path)


def convert_coco_to_funsd(
    src_dir: str, output_path: str, config: object, strip_file_name_path: bool
) -> None:
    """
    Convert CVAT annotated COCO dataset into FUNSD compatible format for finetuning models.
    """
    # instances_default.json
    items = glob.glob(os.path.join(src_dir, "annotations/*.json"))
    if len(items) == 0:
        raise Exception(f"No annotations to process in : {src_dir}")

    os.makedirs(output_path, exist_ok=True)

    for idx, annotations_filename in enumerate(items):
        try:
            print(f"Processing annotation : {annotations_filename}")
            __convert_coco_to_funsd(
                src_dir, output_path, annotations_filename, config, strip_file_name_path
            )
        except Exception as e:
            raise e


def normalize_bbox(bbox, size):
    return [
        int(1000 * bbox[0] / size[0]),
        int(1000 * bbox[1] / size[1]),
        int(1000 * bbox[2] / size[0]),
        int(1000 * bbox[3] / size[1]),
    ]


import io

from PIL import Image


def from_json_file(filename):
    with io.open(filename, "r", encoding="utf-8") as json_file:
        data = json.load(json_file)
        return data


def image_to_byte_array(image: Image) -> bytes:
    imgByteArr = io.BytesIO()
    image.save(imgByteArr, format=image.format)
    imgByteArr = imgByteArr.getvalue()
    return imgByteArr


def extract_icr(image, boxp, icrp):
    if not isinstance(image, np.ndarray):
        raise Exception("Expected image in numpy format")

    msg_bytes = image.tobytes(order="C")
    m = hashlib.sha256()
    m.update(msg_bytes)
    checksum = m.hexdigest()

    print(f"checksum = {checksum}")
    json_file = f"{_tmp_path}/{checksum}.json"
    ensure_exists(f"{_tmp_path}")

    if os.path.exists(json_file):
        json_data = from_json_file(json_file)
        print(f"From JSONFILE : {json_file}")
        boxes = json_data["boxes"]
        result = json_data["result"]
        return boxes, result

    key = checksum
    boxes, img_fragments, lines, _, line_bboxes = boxp.extract_bounding_boxes(
        key, "field", image, PSMode.SPARSE
    )

    # we found no boxes, so we will creat only one box and wrap a whole image as that
    if boxes is None or len(boxes) == 0:
        print(f"Empty boxes for : {checksum}")
        if True:
            file_path = os.path.join(f"{_tmp_path}/snippet", f"empty_boxes-{checksum}.png")
            cv2.imwrite(file_path, image)

        h = image.shape[0]
        w = image.shape[1]
        boxes = [[0, 0, w, h]]
        img_fragments = [image]
        lines = [1]

    result, overlay_image = icrp.recognize(
        key, "test", image, boxes, img_fragments, lines
    )

    data = {"boxes": boxes, "result": result}
    with open(json_file, "w") as f:
        json.dump(
            data,
            f,
            sort_keys=True,
            separators=(",", ": "),
            ensure_ascii=False,
            indent=4,
            cls=NumpyEncoder,
        )

    return boxes, result


def decorate_funsd(src_dir: str, debug_fragments=False):
    work_dir_boxes = ensure_exists(f"{_tmp_path}/boxes")
    work_dir_icr = ensure_exists(f"{_tmp_path}/icr")
    output_ann_dir = ensure_exists(os.path.join(src_dir, "annotations"))

    logger.info("⏳ Decorating examples from = %s", src_dir)
    ann_dir = os.path.join(src_dir, "annotations_tmp")
    img_dir = os.path.join(src_dir, "images")

    if False:
        boxp = BoxProcessorCraft(
            work_dir=work_dir_boxes, models_dir="./model_zoo/craft", cuda=True
        )

    boxp = BoxProcessorUlimDit(
        work_dir=work_dir_boxes,
        # models_dir="./model_zoo/unilm/dit/text_detection",
        cuda=True,
    )

    icrp = TrOcrIcrProcessor(work_dir=work_dir_icr, cuda=True)

    for guid, file in enumerate(sorted(os.listdir(ann_dir))):
        print(f"guid = {guid}")
        print(file)
        if guid == 5:  # TODO: remove box issue solved
            break

        file_path = os.path.join(ann_dir, file)
        with open(file_path, "r", encoding="utf8") as f:
            data = json.load(f)

        image_path = os.path.join(img_dir, file)
        image_path = image_path.replace("json", "png")
        image, size = load_image(image_path)
        # line_numbers : line number associated with bounding box
        # lines : raw line boxes that can be used for further processing
        _, _, line_numbers, _, line_bboxes = boxp.extract_bounding_boxes(
            file, "lines", image, PSMode.MULTI_LINE
        )

        for i, item in enumerate(data["form"]):
            # format : x0,y0,x1,y1
            box = np.array(item["box"]).astype(np.int32)
            x0, y0, x1, y1 = box
            snippet = image[y0:y1, x0:x1, :]
            line_number = find_line_number(line_bboxes, [x0, y0, x1 - x0, y1 - y0])

            # each snippet could be on multiple lines
            print(f"line_number = {line_number}")
            # export cropped region
            if debug_fragments:
                file_path = os.path.join(f"{_tmp_path}/snippet", f"{guid}-snippet_{i}.png")
                cv2.imwrite(file_path, snippet)

            boxes, results = extract_icr(snippet, boxp, icrp)
            results.pop("meta", None)

            if (
                results is None
                or len(results) == 0
                or results["lines"] is None
                or len(results["lines"]) == 0
            ):
                print(f"No results for : {guid}-{i}")
                continue

            words = []
            text = ""

            try:
                text = " ".join([line["text"] for line in results["lines"]])
            except Exception as ex:
                # raise ex
                print(ex)
                # pass

            # boxes are in stored in x0,y0,x1,y1 where x0,y0 is upper left corner and x1,y1 if bottom/right
            # we need to account for offset from the snippet box
            # results["word"] are in a xywh format in local position and need to be converted to relative position
            print("-------------------------------")
            print(results["words"])
            for word in results["words"]:
                w_text = word["text"]
                x, y, w, h = word["box"]
                w_box = [x0 + x, y0 + y, x0 + x + w, y0 + y + h]
                adj_word = {"text": w_text, "box": w_box}
                words.append(adj_word)

            item["words"] = words
            item["text"] = text
            item["line_number"] = line_number

            print(item)

        # create masked image for OTHER label
        image_masked, _ = load_image(image_path)
        index = 0

        for i, item in enumerate(data["form"]):
            # format : x0,y0,x1,y1
            box = np.array(item["box"]).astype(np.int32)
            x0, y0, x1, y1 = box
            cv2.rectangle(
                image_masked, (x0, y0), (x1, y1), (255, 255, 255), thickness=-1
            )
            index = i + 1

        if debug_fragments:
            file_path = os.path.join(f"{_tmp_path}/snippet", f"{guid}-masked.png")
            cv2.imwrite(file_path, image_masked)

        # masked boxes will be same as the original ones
        boxes_masked, results_masked = extract_icr(image_masked, boxp, icrp)

        x0 = 0
        y0 = 0

        print("-------- MASKED ----------")
        for i, word in enumerate(results_masked["words"]):
            w_text = word["text"]
            x, y, w, h = word["box"]
            line_number = find_line_number(line_bboxes, [x, y, w, h])
            w_box = [x0 + x, y0 + y, x0 + x + w, y0 + y + h]
            adj_word = {"text": w_text, "box": w_box}

            item = {
                "id": index + i,
                "text": w_text,
                "box": w_box,
                "line_number": line_number,
                "linking": [],
                "label": "other",
                "words": [adj_word],
            }

            data["form"].append(item)

        # need to reorder items, so they are sorted in proper order Y then X
        lines_unsorted = []
        for i, item in enumerate(data["form"]):
            lines_unsorted.append(item["line_number"])

        lines_unsorted = np.array(lines_unsorted)
        unique_line_ids = sorted(np.unique(lines_unsorted))
        data_form_sorted = []
        word_index = 0

        for i, line_numer in enumerate(unique_line_ids):
            # print(f'line_numer =>  {line_numer}')
            item_pics = []
            box_picks = []

            for j, item in enumerate(data["form"]):
                word_line_number = item["line_number"]
                if line_numer == word_line_number:
                    item_pics.append(item)
                    box_picks.append(item["box"])

            item_pics = np.array(item_pics)
            box_picks = np.array(box_picks)

            indices = np.argsort(box_picks[:, 0])
            item_pics = item_pics[indices]

            for k, item in enumerate(item_pics):
                item["word_index"] = word_index
                data_form_sorted.append(item)
                word_index += 1

        data["form"] = []

        for i, item in enumerate(data_form_sorted):
            data["form"].append(item)
            # print(f"\t=>  {item}")

        json_path = os.path.join(output_ann_dir, file)
        print(json_path)
        with open(json_path, "w") as json_file:
            json.dump(
                data,
                json_file,
                sort_keys=False,
                separators=(",", ": "),
                ensure_ascii=False,
                indent=2,
                cls=NumpyEncoder,
            )


def generate_pan(num_char):
    import string

    letters = string.ascii_letters.lower()
    if np.random.choice([0, 1], p=[0.5, 0.5]):
        letters = string.digits
    if np.random.choice([0, 1], p=[0.5, 0.5]):
        letters = letters.upper()
    prefix = "".join(random.choice(letters) for i in range(num_char))
    return prefix


def load_image_pil(image_path):
    image = Image.open(image_path).convert("RGB")
    w, h = image.size
    return image, (w, h)


def visualize_funsd(src_dir: str, dst_dir: str, config: dict):
    ann_dir = os.path.join(src_dir, "annotations")
    img_dir = os.path.join(src_dir, "images")

    os.makedirs(dst_dir, exist_ok=True)

    for guid, file in enumerate(sorted(os.listdir(ann_dir))):
        file_path = os.path.join(ann_dir, file)

        print(f"file_path : {file_path}")
        with open(file_path, "r", encoding="utf8") as f:
            data = json.load(f)

        filename = file.split("/")[-1].split(".")[0]
        image_path = os.path.join(img_dir, file)
        image_path = image_path.replace("json", "png")
        print(f"image_path : {image_path}")
        print(f"filename : {filename}")
        image, size = load_image_pil(image_path)

        # draw predictions over the image
        draw = ImageDraw.Draw(image, "RGBA")
        font = ImageFont.load_default()
        # https://stackoverflow.com/questions/54165439/what-are-the-exact-color-names-available-in-pils-imagedraw
        label2color = config["label2color"]

        for i, item in enumerate(data["form"]):
            predicted_label = item["label"].lower()
            color = label2color[predicted_label]

            for word in item["words"]:
                box = word["box"]
                draw.rectangle(box, outline=color, width=1)

            box = item["box"]

            if predicted_label != "other":
                draw.rectangle(
                    box,
                    outline=color,
                    width=1,
                )  # fill=(0, 180, 0, 50)
            else:
                draw.rectangle(box, outline=color, width=1)

            predicted_label = f"{i} - {predicted_label}"
            draw.text(
                (box[0] + 10, box[1] - 10),
                text=predicted_label,
                fill=color,
                font=font,
                stroke_width=0,
            )

        image.save(os.path.join(dst_dir, f"viz_{filename}.png"))


@lru_cache(maxsize=10)
def resize_align_bbox(bbox, orig_w, orig_h, target_w, target_h):
    clip_to_y = 1000

    x_scale = target_w / orig_w
    y_scale = target_h / orig_h
    orig_left, orig_top, orig_right, orig_bottom = bbox
    x = int(np.round(orig_left * x_scale))
    y = int(np.round(orig_top * y_scale))
    xmax = int(np.round(orig_right * x_scale))
    ymax = int(np.round(orig_bottom * y_scale))
    return [x, y, xmax, min(ymax, clip_to_y)]


def rescale_annotation_frame(src_json_path: str, src_image_path: str):
    print(
        f"Recalling annotation : {src_json_path.split('/')[-1]}, {src_image_path.split('/')[-1]}"
    )

    filename = src_image_path.split("/")[-1].split(".")[0]
    image, orig_size = load_image_pil(src_image_path)
    resized, target_size = __scale_height(image, 1000)
    resized.save(f"{_tmp_path}/snippet/resized_{filename}.png")

    # print(f"orig_size, target_size   = {orig_size} : {target_size}")
    orig_w, orig_h = orig_size
    target_w, target_h = target_size
    data = from_json_file(src_json_path)

    try:
        for i, item in enumerate(data["form"]):
            bbox = tuple(item["box"])  # np.array(item["box"]).astype(np.int32)
            item["box"] = resize_align_bbox(bbox, orig_w, orig_h, target_w, target_h)
            for word in item["words"]:
                bbox = tuple(word["box"])  # np.array(item["box"]).astype(np.int32)
                word["box"] = resize_align_bbox(
                    bbox, orig_w, orig_h, target_w, target_h
                )
    except Exception as ex:
        print(src_json_path)
        print(ex)
        raise ex

    return data, resized


def __rescale_annotate_frames(
    ann_dir_dest, img_dir_dest, filename, json_path, image_path
):

    # 152630220_3  152618378_2 152618400  152624795_3
    print(f"filename : {filename}")
    print(f"json_path : {json_path}")
    print(f"image_path : {image_path}")

    data, image = rescale_annotation_frame(json_path, image_path)

    # Figure out how to handle this
    # if the width > 1000 SKIP for now
    if max(image.size) > 1000:
        pass
        # print(f"Skipping image due to size[{image.size}] : {filename}")
        # raise Exception(f"Skipping image due to size[{image.size}] : {filename}")
        # return

    json_path_dest = os.path.join(ann_dir_dest, f"{filename}.json")
    image_path_dest = os.path.join(img_dir_dest, f"{filename}.png")
    # save image and json data
    image.save(image_path_dest)

    with open(json_path_dest, "w") as json_file:
        json.dump(
            data,
            json_file,
            sort_keys=True,
            separators=(",", ": "),
            ensure_ascii=False,
            indent=2,
            cls=NumpyEncoder,
        )


def rescale_annotate_frames(src_dir: str, dest_dir: str):
    ann_dir = os.path.join(src_dir, "annotations")
    img_dir = os.path.join(src_dir, "images")

    ann_dir_dest = ensure_exists(os.path.join(dest_dir, "annotations"))
    img_dir_dest = ensure_exists(os.path.join(dest_dir, "images"))

    if False:
        for guid, file in enumerate(sorted(os.listdir(ann_dir))):
            json_path = os.path.join(ann_dir, file)
            filename = file.split("/")[-1].split(".")[0]
            image_path = os.path.join(img_dir, file).replace("json", "png")
            __rescale_annotate_frames(
                ann_dir_dest, img_dir_dest, filename, json_path, image_path
            )

    if True:
        args = []
        for guid, file in enumerate(sorted(os.listdir(ann_dir))):
            json_path = os.path.join(ann_dir, file)
            filename = file.split("/")[-1].split(".")[0]
            image_path = os.path.join(img_dir, file).replace("json", "png")
            __args = (ann_dir_dest, img_dir_dest, filename, json_path, image_path)
            args.append(__args)

        results = []
        start = time.time()
        print("\nPool Executor:")
        print("Time elapsed: %s" % (time.time() - start))

        pool = Pool(processes=mp.cpu_count())
        # pool = Pool(processes=1)
        pool_results = pool.starmap(__rescale_annotate_frames, args)

        pool.close()
        pool.join()

        print("Time elapsed[submitted]: %s" % (time.time() - start))
        for r in pool_results:
            print("Time elapsed[result]: %s  , %s" % (time.time() - start, r))
        print("Time elapsed[all]: %s" % (time.time() - start))


def split_dataset(src_dir, output_path, split_percentage):
    """
    Split CODO dataset for training and test.

    ARGS:
        src_dir  : input folder for COCO dataset, expected structure to have 'annotations' and 'image' folder
        output_path : output folder where new train/test directory will be created
        split_percentage      : split ration ex: .8  this will create 80/20 Train/Test split
    """

    print("Split dataset")
    print("src_dir     = {}".format(src_dir))
    print("output_path = {}".format(output_path))
    print("split       = {}".format(split_percentage))

    ann_dir = os.path.join(src_dir, "annotations")
    img_dir = os.path.join(src_dir, "images")

    if not os.path.exists(ann_dir):
        raise Exception("Source directory missing expected 'annotations' sub-directory")

    if not os.path.exists(img_dir):
        raise Exception("Source directory missing expected 'images' sub-directory")

    file_set = []
    for guid, file in enumerate(sorted(os.listdir(ann_dir))):
        json_path = os.path.join(ann_dir, file)
        image_path = os.path.join(img_dir, file).replace("json", "png")
        filename = image_path.split("/")[-1].split(".")[0]
        item = {"annotation": json_path, "image": image_path, "filename": filename}
        file_set.append(item)

    total_count = len(file_set)
    sample_count = int(total_count * split_percentage)
    print(f"split_percentage = {split_percentage}")
    print(f"total_count      = {total_count}")
    print(f"sample_count     = {sample_count}")
    print(f"output_path      = {output_path}")

    ann_dir_out_train = os.path.join(output_path, "train", "annotations")
    img_dir_out_train = os.path.join(output_path, "train", "images")

    ann_dir_out_test = os.path.join(output_path, "test", "annotations")
    img_dir_out_test = os.path.join(output_path, "test", "images")

    if os.path.exists(os.path.join(output_path, "train")) or os.path.exists(
        os.path.join(output_path, "test")
    ):
        raise Exception(
            "Output directory not empty, manually remove test/train directories."
        )

    os.makedirs(ann_dir_out_train, exist_ok=True)
    os.makedirs(img_dir_out_train, exist_ok=True)
    os.makedirs(ann_dir_out_test, exist_ok=True)
    os.makedirs(img_dir_out_test, exist_ok=True)

    np.random.shuffle(file_set)
    train_set = file_set[0:sample_count]
    test_set = file_set[sample_count:-1]

    print(f"Train size : {len(train_set)}")
    print(f"Test size : {len(test_set)}")

    splits = [
        {
            "name": "train",
            "files": train_set,
            "ann_dir_out": ann_dir_out_train,
            "img_dir_out": img_dir_out_train,
        },
        {
            "name": "test",
            "files": test_set,
            "ann_dir_out": ann_dir_out_test,
            "img_dir_out": img_dir_out_test,
        },
    ]

    for split in splits:
        fileset = split["files"]
        ann_dir_out = split["ann_dir_out"]
        img_dir_out = split["img_dir_out"]

        for item in fileset:
            ann = item["annotation"]
            img = item["image"]
            filename = item["filename"]
            shutil.copyfile(ann, os.path.join(ann_dir_out, f"{filename}.json"))
            shutil.copyfile(img, os.path.join(img_dir_out, f"{filename}.png"))


def default_decorate(args: object):
    print("Default decorate")
    print(args)
    print("*" * 180)

    # This should be our dataset folder
    mode = args.mode
    src_dir = os.path.join(args.dir, f"{mode}")
    decorate_funsd(src_dir, debug_fragments=True)


def default_augment(args: object):
    print("Default augment")
    print(args)
    print("*" * 180)

    # This should be our dataset folder
    mode = args.mode
    aug_count = args.count
    root_dir = args.dir
    src_dir = os.path.join(args.dir, f"{mode}")
    dst_dir = (
        args.dir_output
        if args.dir_output != "./augmented"
        else os.path.abspath(os.path.join(root_dir, f"{mode}-augmented"))
    )

    print(f"mode      = {mode}")
    print(f"aug_count = {aug_count}")
    print(f"src_dir   = {src_dir}")
    print(f"dst_dir   = {dst_dir}")

    # augment_decorated_annotation(count=aug_count, src_dir=src_dir, dest_dir=dst_dir)


def default_rescale(args: object):
    print("Default rescale")
    print(args)
    print("*" * 180)

    # This should be our dataset folder
    mode = args.mode
    suffix = args.suffix
    root_dir = args.dir
    src_dir = os.path.join(args.dir, f"{mode}{suffix}")

    dst_dir = (
        args.dir_output
        if args.dir_output != "./rescaled"
        else os.path.abspath(os.path.join(root_dir, f"{mode}-rescaled"))
    )

    print(f"mode    = {mode}")
    print(f"suffix  = {suffix}")
    print(f"src_dir = {src_dir}")
    print(f"dst_dir = {dst_dir}")

    rescale_annotate_frames(src_dir=src_dir, dest_dir=dst_dir)


def default_visualize(args: object):
    print("Default visualize")
    print(args)
    print("*" * 180)

    src_dir = args.dir
    dst_dir = args.dir_output

    print(f"src_dir   = {src_dir}")
    print(f"dst_dir   = {dst_dir}")
    print(f"config    = {args.config}")
    # load config file
    config = from_json_file(args.config)

    visualize_funsd(src_dir, dst_dir, config)


def default_convert(args: object):
    print("Default convert")
    print(args)
    print("*" * 180)
    mode = args.mode
    suffix = args.mode_suffix
    strip_file_name_path = args.strip_file_name_path
    src_dir = os.path.join(args.dir, f"{mode}{suffix}")

    dst_path = (
        args.dir_converted
        if args.dir_converted != "./converted"
        else os.path.join(args.dir, "output", "dataset", f"{mode}")
    )

    if not os.path.exists(args.config):
        raise FileNotFoundError(f"File not found : {args.config}")

    # load config file
    config = from_json_file(args.config)

    print(f"mode       = {mode}")
    print(f"suffix     = {suffix}")
    print(f"src_dir    = {src_dir}")
    print(f"dst_path   = {dst_path}")

    convert_coco_to_funsd(src_dir, dst_path, config, strip_file_name_path)


def default_all_steps(args: object):
    from argparse import Namespace

    print("Default all_steps")
    print(args)
    print("*" * 180)

    root_dir = args.dir
    aug_count = args.aug_count
    dataset_dir = os.path.join(root_dir, "output", "dataset")

    # clone and remove  unused values
    args_1 = vars(args).copy()
    args_1["func"] = None
    args_1["command"] = "convert"
    args_1["dir_converted"] = "./converted"

    args_2 = vars(args).copy()
    args_2["func"] = None
    args_2["command"] = "decorate"
    args_2["dir"] = dataset_dir

    args_3 = vars(args).copy()
    args_3["func"] = None
    args_3["command"] = "augment"
    args_3["dir"] = dataset_dir
    args_3["count"] = aug_count
    args_3["dir_output"] = "./augmented"

    args_4 = vars(args).copy()
    args_4["func"] = None
    args_4["command"] = "rescale"
    args_4["dir"] = dataset_dir
    args_4["dir_output"] = "./rescaled"
    args_4["suffix"] = "-augmented"

    # execute each step
    # default_convert(Namespace(**args_1))
    default_decorate(Namespace(**args_2))
    default_augment(Namespace(**args_3))
    default_rescale(Namespace(**args_4))


def default_split(args: object):
    print("Default split")
    print(args)
    print("*" * 180)

    src_dir = args.dir
    dst_dir = args.dir_output
    ratio = args.ratio

    print(f"src_dir = {src_dir}")
    print(f"dst_dir = {dst_dir}")
    print(f"ratio   = {ratio}")

    split_dataset(src_dir, dst_dir, ratio)


def extract_args(args=None) -> object:
    """
    Argument parser

    PYTHONPATH="$PWD" python ./marie/coco_funsd_converter.py --mode test --step augment --strip_file_name_path true --dir ~/dataset/private/corr-indexer --config ~/dataset/private/corr-indexer/config.json --aug-count 2
    """
    parser = argparse.ArgumentParser(
        prog="coco_funsd_converter", description="COCO to FUNSD conversion utility"
    )

    subparsers = parser.add_subparsers(
        dest='command', help='Commands to run', required=True
    )

    convert_parser = subparsers.add_parser(
        "convert", help="Convert documents from COCO to FUNSD-Like intermediate format"
    )

    convert_parser.set_defaults(func=default_convert)

    convert_parser.add_argument(
        "--mode",
        required=True,
        type=str,
        default="train",
        help="Conversion mode : train/test/validate/etc",
    )

    convert_parser.add_argument(
        "--mode-suffix",
        required=False,
        type=str,
        default="-deck-raw",
        help="Suffix for the mode",
    )

    convert_parser.add_argument(
        "--strip_file_name_path",
        required=True,
        # type=bool,
        # action='store_true',
        type=lambda x: bool(distutils.util.strtobool(x)),
        default=False,
        help="Should full image paths be striped from annotations file",
    )

    convert_parser.add_argument(
        "--dir",
        required=True,
        type=str,
        default="~/dataset/ds-001/indexer",
        help="Base data directory",
    )

    convert_parser.add_argument(
        "--dir-converted",
        required=False,
        type=str,
        default="./converted",
        help="Converted data directory",
    )

    convert_parser.add_argument(
        "--config",
        required=True,
        type=str,
        default='./config.json',
        help="Configuration file used for conversion",
    )

    decorate_parser = subparsers.add_parser(
        "decorate", help="Decorate documents(Box detection, ICR)"
    )
    decorate_parser.set_defaults(func=default_decorate)

    decorate_parser.add_argument(
        "--mode",
        required=True,
        type=str,
        default="train",
        help="Conversion mode : train/test/validate/etc",
    )

    decorate_parser.add_argument(
        "--dir",
        required=True,
        type=str,
        help="Base dataset directory where the document for decorating resize",
    )

    rescale_parser = subparsers.add_parser(
        "rescale", help="Rescale/Normalize documents to be used by UNILM"
    )
    rescale_parser.set_defaults(func=default_rescale)

    rescale_parser.add_argument(
        "--mode",
        required=True,
        type=str,
        help="Conversion mode : train/test/validate/etc",
    )

    rescale_parser.add_argument(
        "--dir",
        required=True,
        type=str,
        help="Source directory",
    )

    rescale_parser.add_argument(
        "--dir-output",
        default="./rescaled",
        type=str,
        help="Destination directory",
    )

    rescale_parser.add_argument(
        "--suffix",
        default="-augmented",
        type=str,
        help="Suffix to append to the source directory",
    )

    visualize_parser = subparsers.add_parser("visualize", help="Visualize documents")
    visualize_parser.set_defaults(func=default_visualize)

    visualize_parser.add_argument(
        "--dir",
        required=True,
        type=str,
        help="Source directory",
    )

    visualize_parser.add_argument(
        "--dir-output",
        default=f"{_tmp_path}/visualize",
        type=str,
        help="Destination directory",
    )

    visualize_parser.add_argument(
        "--config",
        type=str,
        default='./visualize-config.json',
        help="Configuration file used for conversion",
    )

    split_parser = subparsers.add_parser(
        "split", help="Split COCO dataset into train/test"
    )
    split_parser.set_defaults(func=default_split)

    split_parser.add_argument(
        "--dir",
        required=True,
        type=str,
        help="Source directory",
    )

    split_parser.add_argument(
        "--dir-output",
        default=f"{_tmp_path}/split",
        type=str,
        help="Destination directory",
    )

    split_parser.add_argument(
        "--ratio",
        default=0.8,
        type=float,
        help="Destination directory",
    )

    convert_all_parser = subparsers.add_parser(
        "convert-all",
        help="Run all conversion phases[convert,decorate,augment,rescale] using most defaults.",
    )

    convert_all_parser.set_defaults(func=default_all_steps)

    convert_all_parser.add_argument(
        "--mode",
        required=True,
        type=str,
        default="train",
        help="Conversion mode : train/test/validate/etc",
    )

    convert_all_parser.add_argument(
        "--mode-suffix",
        required=False,
        type=str,
        default="-deck-raw",
        help="Suffix for the mode",
    )

    convert_all_parser.add_argument(
        "--strip_file_name_path",
        required=True,
        # type=bool,
        # action='store_true',
        type=lambda x: bool(distutils.util.strtobool(x)),
        default=False,
        help="Should full image paths be striped from annotations file",
    )

    convert_all_parser.add_argument(
        "--aug-count",
        required=True,
        type=int,
        help="Number of augmentations per annotation",
    )

    convert_all_parser.add_argument(
        "--dir",
        required=True,
        type=str,
        default="~/dataset/ds-001/indexer",
        help="Base data directory",
    )

    convert_all_parser.add_argument(
        "--config",
        required=True,
        type=str,
        default='./config.json',
        help="Configuration file used for conversion",
    )

    try:
        return parser.parse_args(args) if args else parser.parse_args()
    except:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    args = extract_args()
    print("-" * 120)
    print(args)
    print("-" * 120)

    args.func(args)