import argparse
import os
import json
from collections import defaultdict
from pprint import pprint
import re

import numpy as np

from utils import get_pbar


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir")
    parser.add_argument("target_dir")
    parser.add_argument("--min_count", type=int, default=5)
    return parser.parse_args()


def _tokenize(raw):
    tokens = re.findall(r"[\w]+", raw)
    tokens = [token.lower() for token in tokens]
    return tokens


def _vget(vocab_dict, word):
    return vocab_dict[word] if word in vocab_dict else 0


def _vlup(vocab_dict, words):
    return [_vget(vocab_dict, word) for word in words]


def _get_text(vocab_dict, anno, key):
    if key[0] == 'T':
        value = anno['text'][key]['value']
        return _vlup(vocab_dict, _tokenize(value))
    elif key[0] == 'O':
        if 'text' in anno['objects'][key]:
            new_key = anno['objects'][key]['text'][0]
            return _get_text(vocab_dict, anno, new_key)
    return []


def _get_center(anno, key):
    type_dict = {'T': 'text', 'A': 'arrows', 'B': 'blobs', 'H': 'arrowHeads', 'R': 'regions', 'O': 'objects'}
    poly_dict = {'T': 'rectangle', 'A': 'polygon', 'B': 'polygon', 'H': 'rectangle', 'R': 'polygon'}
    type_ = type_dict[key[0]]
    if type_ == 'objects':
        if 'blobs' in anno[type_][key] and len(anno[type_][key]['blobs']) > 0:
            new_key = anno[type_][key]['blobs'][0]
        elif 'text' in anno[type_][key]:
            new_key = anno[type_][key]['text'][0]
        else:
            raise Exception("%r" % anno)
        return _get_center(anno, new_key)
    shape = poly_dict[key[0]]
    poly = np.array(anno[type_][key][shape])
    center = map(int, map(round, np.mean(poly, 0)))
    return center


def _get_head_center(anno, arrow_key):
    if len(anno['arrows'][arrow_key]['arrowHeads']) == 0:
        return [0, 0]
    head_key = anno['arrows'][arrow_key]['arrowHeads'][0]
    return _get_center(anno, head_key)


def _get_1hot_vector(dim, idx):
    arr = [0] * dim
    arr[idx] = 1
    return arr


def prepro_annos(args):
    """
    for each annotation file,
    [{'type': one-hot-in-4-vector,
      'r0': rect,
      'r1': rect,
      'rh': rect,
      'ra': rect,
      't0': indexed_words,
      't1': indexed_words}]

    one-hot-in-4-vector: [intraLabel, intraRegionLabel, interLinkage, intraLinkage,] (arrowDescriptor, arrowHeadTail)
    :param args:
    :return:
    """
    data_dir = args.data_dir
    target_dir = args.target_dir
    vocab_path = os.path.join(target_dir, "vocab.json")
    vocab = json.load(open(vocab_path, "rb"))
    relations_path = os.path.join(target_dir, "relations.json")

    relations_dict = {}
    dim = 4
    hot_index_dict = {('intraObject', 'label', 'objectDescription'): 0,
                      ('intraObject', 'label', 'regionDescriptionNoArrow'): 1,
                      ('interObject', 'linkage', 'objectToObject'): 2,
                      ('intraObject', 'linkage', 'regionDescription'): 3,
                      ('intraObject', 'linkage', 'objectDescription'): 3,
                      ('intraObject', 'textLinkage', 'textDescription'): 3}

    annos_dir = os.path.join(data_dir, "annotations")
    anno_names = os.listdir(annos_dir)
    pbar = get_pbar(len(anno_names))
    pbar.start()
    for i, anno_name in enumerate(anno_names):
        image_name = os.path.splitext(anno_name)[0]
        image_id = os.path.splitext(image_name)[0]
        anno_path = os.path.join(annos_dir, anno_name)
        anno = json.load(open(anno_path, "rb"))
        relations = []
        if 'relationships' not in anno:
            continue
        for rel_type, d in anno['relationships'].iteritems():
            for rel_subtype, dd in d.iteritems():
                if len(dd) == 0:
                    continue
                for rel_key, ddd in dd.iteritems():
                    category = ddd['category']
                    # FIXME : just choose one for now
                    origin_key = ddd['origin'][0]
                    dest_key = ddd['destination'][0]
                    origin_center = _get_center(anno, origin_key)
                    dest_center = _get_center(anno, dest_key)
                    if 'connector' in ddd:
                        arrow_key = ddd['connector'][0]
                        arrow_center = _get_center(anno, arrow_key)
                        head_center = _get_head_center(anno, arrow_key)
                    else:
                        arrow_center = [0, 0]
                        head_center = [0, 0]
                    idx = hot_index_dict[(rel_type, rel_subtype, category)]
                    # type_ = _get_1hot_vector(dim, idx)
                    type_ = idx
                    origin_text = _get_text(vocab, anno, origin_key)
                    dest_text = _get_text(vocab, anno, dest_key)
                    relation = dict(type=type_, r0=origin_center, r1=dest_center, rh=head_center, ra=arrow_center,
                                    t0=origin_text, t1=dest_text)
                    relations.append(relation)
        # TODO : arrow relations as well?
        relations_dict[image_id] = relations
        pbar.update(i)
    pbar.finish()

    print("dumping json file ... ")
    json.dump(relations_dict, open(relations_path, 'wb'))
    print("done")


def prepro_questions(args):
    data_dir = args.data_dir
    target_dir = args.target_dir
    questions_dir = os.path.join(data_dir, "questions")
    questions_path = os.path.join(target_dir, "questions.json")
    vocab_path = os.path.join(target_dir, "vocab.json")
    vocab = json.load(open(vocab_path, "rb"))

    questions_dict = {'sents': {},
                      'answers': {}}

    ques_names = os.listdir(questions_dir)
    question_id = 0
    max_sent_size = 0
    pbar = get_pbar(len(ques_names))
    pbar.start()
    for i, ques_name in enumerate(ques_names):
        if os.path.splitext(ques_name)[1] != ".json":
            pbar.update(i)
            continue
        ques_path = os.path.join(questions_dir, ques_name)
        ques = json.load(open(ques_path, "rb"))
        for ques_text, d in ques['questions'].iteritems():
            ques_words = _tokenize(ques_text)
            choice_wordss = [_tokenize(choice) for choice in d['answerTexts']]
            sents = [_vlup(vocab, ques_words + choice_words) for choice_words in choice_wordss]
            # TODO : one hot vector or index?
            questions_dict['answers'][str(question_id)] = d['correctAnswer']
            question_id += 1
            max_sent_size = max(max_sent_size, max(len(sent) for sent in sents))
        pbar.update(i)
    pbar.finish()
    questions_dict['max_sent_size'] = max_sent_size

    print("number of questions: %d" % len(questions_dict['answers']))
    print("max sent size: %d" % max_sent_size)
    print("dumping json file ... ")
    json.dump(questions_dict, open(questions_path, "wb"))
    print("done")


def build_vocab(args):
    data_dir = args.data_dir
    target_dir = args.target_dir
    min_count = args.min_count
    vocab_path = os.path.join(target_dir, "vocab.json")
    questions_dir = os.path.join(data_dir, "questions")
    annos_dir = os.path.join(data_dir, "annotations")

    vocab_counter = defaultdict(int)
    anno_names = os.listdir(annos_dir)
    pbar = get_pbar(len(anno_names))
    pbar.start()
    for i, anno_name in enumerate(anno_names):
        if os.path.splitext(anno_name)[1] != ".json":
            pbar.update(i)
            continue
        anno_path = os.path.join(annos_dir, anno_name)
        anno = json.load(open(anno_path, "rb"))
        for _, d in anno['text'].iteritems():
            text = d['value']
            for word in _tokenize(text):
                vocab_counter[word] += 1
        pbar.update(i)
    pbar.finish()

    ques_names = os.listdir(questions_dir)
    pbar = get_pbar(len(ques_names))
    pbar.start()
    for i, ques_name in enumerate(ques_names):
        if os.path.splitext(ques_name)[1] != ".json":
            pbar.update(i)
            continue
        ques_path = os.path.join(questions_dir, ques_name)
        ques = json.load(open(ques_path, "rb"))
        for ques_text, d in ques['questions'].iteritems():
            for word in _tokenize(ques_text): vocab_counter[word] += 1
            for choice in d['answerTexts']:
                for word in _tokenize(choice): vocab_counter[word] += 1
        pbar.update(i)
    pbar.finish()

    vocab_list = zip(*sorted([pair for pair in vocab_counter.iteritems() if pair[1] > min_count],
                             key=lambda x: -x[1]))[0]

    vocab_dict = {word: idx+1 for idx, word in enumerate(sorted(vocab_list))}
    vocab_dict['UNK'] = 0
    print("vocab size: %d" % len(vocab_dict))
    json.dump(vocab_dict, open(vocab_path, "wb"))


if __name__ == "__main__":
    ARGS = get_args()
    build_vocab(ARGS)
    prepro_questions(ARGS)
    prepro_annos(ARGS)