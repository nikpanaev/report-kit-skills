#!/usr/bin/env python3
"""Один длинный PNG из прокрученных кадров: общий заголовок один раз, без повторов."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from private_paths import outside_package

import numpy as np
from PIL import Image, ImageFilter


def rgb(source):
    if isinstance(source, Image.Image):
        return source.convert('RGB')
    with Image.open(source) as image:
        return image.convert('RGB')


def body(path, header):
    image = rgb(path)
    try:
        return np.asarray(image)[header:]
    finally:
        image.close()


def stitch(images, header, left, right):
    paths = images
    if not paths or header < 0:
        raise ValueError('Нужны кадры и неотрицательная высота заголовка')
    sizes = []
    for path in paths:
        if isinstance(path, Image.Image):
            sizes.append(path.size)
        else:
            with Image.open(path) as image:
                sizes.append(image.size)
    width = sizes[0][0]
    if not 0 <= left < right <= width:
        raise ValueError('Область сопоставления должна находиться внутри изображения')
    if any(w != width or h <= header + 300 for w, h in sizes):
        raise ValueError('Кадры должны иметь одинаковую ширину и достаточно содержимого')
    previous = body(paths[0], header)
    with Image.fromarray(previous) as frame, frame.filter(ImageFilter.GaussianBlur(.7)) as blurred:
        previous_match = np.asarray(blurred)
    pieces = [(0, 0, sizes[0][1])]
    total = sizes[0][1]
    joins = []
    for index, path in enumerate(paths[1:], 1):
        following = body(path, header)
        with Image.fromarray(following) as frame, frame.filter(ImageFilter.GaussianBlur(.7)) as blurred:
            following_match = np.asarray(blurred)
        candidates = []
        template_height = None
        for shift in range(1, len(previous) - 127):
            overlap = len(previous) - shift
            height = min(overlap - 32, 200, len(following) - 32)
            if height != template_height:
                template = following_match[32:32 + height:2, left:right:4].astype(float)
                contrast = template.std(axis=(0, 1)).mean()
                template_height = height
            if contrast < 2:
                continue
            comparison = previous_match[shift + 32:shift + 32 + height:2, left:right:4].astype(float)
            candidates.append((float(np.abs(comparison - template).mean()), shift, overlap))
        if not candidates:
            raise ValueError('Недостаточно различимого перекрытия: переснимите соседние кадры')
        candidates.sort()
        score, shift, overlap = candidates[0]
        alternatives = [c for c in candidates if abs(c[1] - shift) > 4]
        if score > 6 or (alternatives and alternatives[0][0] - score < .5):
            raise ValueError(f'Неуверенное совпадение кадров (ошибка {score:.2f}): переснимите')
        center = overlap // 2
        rows = range(max(1, center - 32), min(overlap - 1, center + 33))
        seam = min(rows, key=lambda y: (
            following[y:y + 1, left:right].astype(float).std(axis=(0, 1)).mean(), abs(y - center)))
        cut = total - overlap + seam
        while pieces and total > cut:
            frame, start, end = pieces.pop()
            size = end - start
            retained = size - (total - cut)
            total -= size
            if retained > 0:
                pieces.append((frame, start, start + retained))
                total += retained
        pieces.append((index, header + seam, sizes[index][1]))
        total += sizes[index][1] - header - seam
        joins.append(dict(shift=shift, overlap=overlap, seam=seam, error=round(score, 3)))
        previous, previous_match = following, following_match
    del previous, previous_match
    if len(paths) > 1:
        del following, following_match, template, comparison
    result = Image.new('RGB', (width, total))
    top = 0
    for index, start, end in pieces:
        image = rgb(paths[index])
        try:
            cropped = image.crop((0, start, width, end))
            result.paste(cropped, (0, top))
            cropped.close()
        finally:
            image.close()
        top += end - start
    assert top == total
    return result, joins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', nargs='+', type=Path, help='Кадры в порядке прокрутки сверху вниз')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--header', type=int, required=True, help='Высота неподвижного заголовка в px')
    parser.add_argument('--match-left', type=int, required=True)
    parser.add_argument('--match-right', type=int, required=True)
    args = parser.parse_args()
    try:
        args.output = outside_package(args.output)
        images = args.images
        result, joins = stitch(images, args.header, args.match_left, args.match_right)
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            result.save(args.output)
            print(json.dumps({"ok": True, "path": str(args.output.resolve()),
                              "size": result.size, "joins": joins}, ensure_ascii=False))
        finally:
            result.close()
    except (OSError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
