import glob
import os

import task
import deit
import trocr_models
import torch
import fairseq
from fairseq import utils
from fairseq_cli import generate
from PIL import Image
import torchvision.transforms as transforms


def init(model_path, beam=5):
    model, cfg, task = fairseq.checkpoint_utils.load_model_ensemble_and_task(
        [model_path],
        arg_overrides={"beam": beam, "task": "text_recognition", "data": "", "fp16": False})

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model[0].to(device)

    img_transform = transforms.Compose([
        transforms.Resize((384, 384), interpolation=3),
        transforms.ToTensor(),
        transforms.Normalize(0.5, 0.5)
    ])

    generator = task.build_generator(
        model, cfg.generation, extra_gen_cls_kwargs={'lm_model': None, 'lm_weight': None}
    )

    bpe = task.build_bpe(cfg.bpe)

    return model, cfg, task, generator, bpe, img_transform, device


def preprocess(img_path, img_transform):
    im = Image.open(img_path).convert('RGB').resize((384, 384))
    im = img_transform(im).unsqueeze(0).to(device).float()

    sample = {
        'net_input': {"imgs": im},
    }

    return sample


def get_text(cfg, generator, model, sample, bpe):
    decoder_output = task.inference_step(generator, model, sample, prefix_tokens=None, constraints=None)
    decoder_output = decoder_output[0][0]       #top1

    hypo_tokens, hypo_str, alignment = utils.post_process_prediction(
        hypo_tokens=decoder_output["tokens"].int().cpu(),
        src_str="",
        alignment=decoder_output["alignment"],
        align_dict=None,
        tgt_dict=model[0].decoder.dictionary,
        remove_bpe=cfg.common_eval.post_process,
        extra_symbols_to_ignore=generate.get_symbols_to_strip_from_output(generator),
    )

    detok_hypo_str = bpe.decode(hypo_str)

    return detok_hypo_str


if __name__ == '__main__':
    model_path = '/home/gbugaj/devio/3rdparty/unilm/models/trocr-large-printed.pt'
    # model_path = '/home/gbugaj/devio/3rdparty/unilm/models/trocr-small-printed.pt'

    jpg_path = "/home/gbugaj/devio/marie-icr/assets/psm/word/0001.jpg"
    jpg_path = "/home/gbugaj/devio/marie-icr/assets/english/Lines/004.png"
    # jpg_path = "/opt/grapnel/debug-x1/0001/340551352.png"
    beam = 5

    model, cfg, task, generator, bpe, img_transform, device = init(model_path, beam)
    _path =  jpg_path

    sample = preprocess(_path, img_transform)
    text = get_text(cfg, generator, model, sample, bpe)
    print(f"format : {text}  >> {_path}")

    os.exit(0) 
    burst_dir = "/tmp/boxes/PID_576_7188_0_150459314_page_0004/bounding_boxes/field/crop"

    for _path in sorted(glob.glob(os.path.join(burst_dir, "*.*"))):
        sample = preprocess(_path, img_transform)
        text = get_text(cfg, generator, model, sample, bpe)
        print(f"format : {text}  >> {_path}")

    print('done')

