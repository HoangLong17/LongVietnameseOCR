"""
Copyright (c) Facebook, Inc. and its affiliates.

This source code is licensed under the MIT license found in the
LICENSE file in the root directory of this source tree.
"""

import argparse
import editdistance
import json
import os
import torch
import sys

import models
import utils

import matplotlib.pyplot as plt
from PIL import Image

sys.path.append("../vietocr")
from vietocr.tool.predictor import Predictor
from vietocr.tool.config import Cfg



def parse_args():
    parser = argparse.ArgumentParser(
        description="Evalaute a handwriting recognition model."
    )
    parser.add_argument(
        "--config", type=str, help="The json configuration file used for training."
    )
    parser.add_argument("--disable_cuda", action="store_true", help="Disable CUDA")
    parser.add_argument(
        "--checkpoint_path",
        default="/tmp/",
        type=str,
        help="Checkpoint path for loading the model",
    )
    parser.add_argument(
        "--load_last",
        default=False,
        action="store_true",
        help="Load the last saved model instead of the best model.",
    )
    parser.add_argument(
        "--split",
        default="validation",
        type=str,
        choices=["train", "validation", "test"],
        help="Data split to test on (default: 'validation')",
    )
    args = parser.parse_args()
    return args


@torch.no_grad()
def test(args):
    with open(args.config, "r") as fid:
        config = json.load(fid)

    if not args.disable_cuda:
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")

    #load vietocr config
    vietocr_config = Cfg.load_config_from_name('vgg_transformer')
    
    vietocr_config['weights'] = 'https://drive.google.com/uc?id=13327Y1tz1ohsm5YZMyXVMPIOjoOA0OaA'
    vietocr_config['cnn']['pretrained']=False
    vietocr_config['device'] = 'cuda:0'
    vietocr_config['predictor']['beamsearch']=False

    dataset = config["data"]["dataset"]
    if not os.path.exists(f"datasets/{dataset}.py"):
        raise ValueError(f"Unknown dataset {dataset}")
    dataset = utils.module_from_file("dataset", f"datasets/{dataset}.py")

    input_size = config["data"]["num_features"]
    data_path = config["data"]["data_path"]
    preprocessor = dataset.Preprocessor(
        data_path,
        num_features=input_size,
        tokens_path=config["data"].get("tokens", None),
        lexicon_path=config["data"].get("lexicon", None),
        use_words=config["data"].get("use_words", False),
        prepend_wordsep=config["data"].get("prepend_wordsep", False),
    )
    data = dataset.Dataset(data_path, preprocessor, split=args.split, config=vietocr_config)
    loader = utils.data_loader(data, config)

    criterion, output_size = utils.load_criterion(
        config.get("criterion_type", "ctc"),
        preprocessor,
        config.get("criterion", {}),
    )
    criterion = criterion.to(device)
    # model = utils.load_model(
    #     config["model_type"], input_size, output_size, config["model"]
    # ).to(device)
    # models.load_from_checkpoint(model, criterion, args.checkpoint_path, args.load_last)
    
    #load model from vietocr
    model = Predictor(vietocr_config)

    model.model.eval()
    meters = utils.Meters()
    for inputs, targets in loader:
        outputs = model.predict(inputs.to(device))
        meters.loss += criterion(outputs, targets).item() * len(targets)
        meters.num_samples += len(targets)
        predictions = criterion.viterbi(outputs)
        for p, t in zip(predictions, targets):
            p, t = preprocessor.tokens_to_text(p), preprocessor.to_text(t)
            pw, tw = p.split(preprocessor.wordsep), t.split(preprocessor.wordsep)
            pw, tw = list(filter(None, pw)), list(filter(None, tw))
            tokens_dist = editdistance.eval(p, t)
            words_dist = editdistance.eval(pw, tw)
            print("CER: {:.3f}".format(tokens_dist * 100.0 / len(t) if len(t) > 0 else 0))
            print("WER: {:.3f}".format(words_dist * 100.0 / len(tw) if len(tw) > 0 else 0))
            print("HYP:", "".join(p))
            print("REF", "".join(t))
            print("=" * 80)
            meters.edit_distance_tokens += tokens_dist
            meters.edit_distance_words += words_dist
            meters.num_tokens += len(t)
            meters.num_words += len(tw)

    print(
        "Loss {:.3f}, CER {:.3f}, WER {:.3f}, ".format(
            meters.avg_loss, meters.cer, meters.wer
        )
    )


def main():
    args = parse_args()
    test(args)


if __name__ == "__main__":
    main()
