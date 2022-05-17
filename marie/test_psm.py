import os

import cv2
from boxes.craft_box_processor import BoxProcessorCraft, PSMode
from document.craft_icr_processor import CraftIcrProcessor
from utils.utils import ensure_exists


if __name__ == '__main__':

    work_dir_boxes = ensure_exists('/tmp/boxes')
    work_dir_icr = ensure_exists('/tmp/icr')
    img_path = './assets/psm/word/0001.png'

    if not os.path.exists(img_path):
        raise Exception(f'File not found : {img_path}')

    key = img_path.split('/')[-1]
    snippet = cv2.imread(img_path)

    box = BoxProcessorCraft(work_dir=work_dir_boxes, models_dir='./model_zoo/craft')
    icr = CraftIcrProcessor(work_dir=work_dir_icr, cuda=False)

    boxes, img_fragments, lines, _ = box.extract_bounding_boxes(
        key, 'field', snippet, PSMode.WORD)

    print(boxes)
    icr.recognize(key, 'test', snippet, boxes, img_fragments, lines)
