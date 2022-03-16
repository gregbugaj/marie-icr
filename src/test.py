
import json
import os
import argparse
import glob
import numpy as np
import cv2

from utils.utils import current_milli_time, ensure_exists
from utils.image_utils import read_image

from boxes.box_processor import BoxProcessor
from document.icr_processor import IcrProcessor

if __name__ == '__main__':

    work_dir_boxes = ensure_exists('/tmp/boxes')
    work_dir_icr = ensure_exists('/tmp/icr')
    img_path='./examples/set-001/test/fragment-001.png'

    if True:
        if not os.path.exists(img_path):
            raise Exception(f'File not found : {img_path}')

        key = img_path.split('/')[-1]
        snippet = cv2.imread(img_path)

        box = BoxProcessor(work_dir=work_dir_boxes, models_dir='./models/craft')
        icr = IcrProcessor(work_dir=work_dir_icr, cuda=False)

        boxes, img_fragments, lines, _ = box.extract_bounding_boxes(key, 'field', snippet)
        icr.recognize(key, 'test', snippet, boxes, img_fragments, lines)
