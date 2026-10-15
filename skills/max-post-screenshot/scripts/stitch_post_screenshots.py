#!/usr/bin/env python3
"""Один длинный PNG из прокрученных кадров: общий заголовок один раз, без повторов."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_shared'))
from private_paths import outside_package

from PIL import Image, ImageChops, ImageFilter, ImageStat


def rgb(source):
    if isinstance(source, Image.Image):
        return source.convert('RGB')
    with Image.open(source) as image:
        return image.convert('RGB')


def body(path, header):
    with rgb(path) as image:
        return image.crop((0, header, image.width, image.height))


def sample(image, top, height, left, right):
    # Pillow maps pixel centres; offsets preserve the original [::2, ::4] grid.
    return image.transform(((right - left + 3) // 4, (height + 1) // 2),
                           Image.Transform.AFFINE, (4, 0, left - 1.5, 0, 2, top - .5),
                           resample=Image.Resampling.NEAREST)


def contrast(image):
    return sum(ImageStat.Stat(image).stddev) / 3


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
    previous_match = previous.filter(ImageFilter.GaussianBlur(.7))
    pieces = [(0, 0, sizes[0][1])]
    total = sizes[0][1]
    joins = []
    following = following_match = template = None
    try:
        for index, path in enumerate(paths[1:], 1):
            following = body(path, header)
            following_match = following.filter(ImageFilter.GaussianBlur(.7))
            candidates = []
            template_height = None
            for shift in range(1, previous.height - 127):
                overlap = previous.height - shift
                height = min(overlap - 32, 200, following.height - 32)
                if height != template_height:
                    if template is not None: template.close()
                    template = sample(following_match, 32, height, left, right)
                    variation = contrast(template)
                    template_height = height
                if variation < 2:
                    continue
                with sample(previous_match, shift + 32, height, left, right) as comparison:
                    with ImageChops.difference(comparison, template) as difference:
                        score = sum(ImageStat.Stat(difference).mean) / 3
                candidates.append((score, shift, overlap))
            if not candidates:
                raise ValueError('Недостаточно различимого перекрытия: переснимите соседние кадры')
            candidates.sort()
            score, shift, overlap = candidates[0]
            alternatives = [c for c in candidates if abs(c[1] - shift) > 4]
            if score > 6 or (alternatives and alternatives[0][0] - score < .5):
                raise ValueError(f'Неуверенное совпадение кадров (ошибка {score:.2f}): переснимите')
            center = overlap // 2
            rows = range(max(1, center - 32), min(overlap - 1, center + 33))
            def row_score(y):
                with following.crop((left, y, right, y + 1)) as row:
                    return contrast(row), abs(y - center)
            seam = min(rows, key=row_score)
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
            previous.close(); previous_match.close()
            previous, previous_match = following, following_match
            following = following_match = None
    finally:
        for image in (previous, previous_match, following, following_match, template):
            if image is not None: image.close()
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
