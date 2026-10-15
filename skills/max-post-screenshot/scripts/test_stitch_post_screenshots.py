"""Проверка: один заголовок, точный исходный контент и отказ для чужого кадра."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import random
from PIL import Image
from stitch_post_screenshots import stitch, sample


def check():
    rng = random.Random(42)
    header = Image.new('RGB', (160, 40), (230, 230, 230))
    content = Image.frombytes('RGB', (160, 1100), rng.randbytes(1100 * 160 * 3))
    def make_frame(start, height=500, source=content):
        result = Image.new('RGB', (160, height + 40))
        result.paste(header, (0, 0))
        with source.crop((0, start, 160, start + height)) as crop:
            result.paste(crop, (0, 40))
        return result
    frames = [make_frame(start) for start in (0, 300, 600)]
    result, joins = stitch(frames, 40, 10, 150)
    assert result.tobytes() == header.tobytes() + content.tobytes()
    assert [j['overlap'] for j in joins] == [200, 200]
    for starts, heights in (((0,), (500,)),
                            ((0, 50, 100, 150), (500, 500, 500, 500)),
                            ((0, 200, 400), (600, 500, 650))):
        varied = [make_frame(start, height) for start, height in zip(starts, heights)]
        combined, _ = stitch(images=varied, header=40, left=10, right=150)
        with content.crop((0, 0, 160, starts[-1] + heights[-1])) as expected:
            assert combined.tobytes() == header.tobytes() + expected.tobytes()
        assert all(image.getpixel((0, 0)) == (230, 230, 230) for image in varied)
        combined.close()
        for image in varied: image.close()
    with tempfile.TemporaryDirectory(prefix='stitch-check-') as directory:
        paths = [Path(directory) / f'{i}.png' for i in range(len(frames))]
        output = Path(directory) / 'result.png'
        for frame, path in zip(frames, paths):
            frame.save(path)
        from_paths, path_joins = stitch(paths, 40, 10, 150)
        assert from_paths.tobytes() == result.tobytes() and path_joins == joins
        run = subprocess.run([sys.executable, str(Path(__file__).with_name('stitch_post_screenshots.py')),
                              *map(str, paths), '--header', '40', '--match-left', '10',
                              '--match-right', '150', '--output', str(output)], capture_output=True, text=True)
        assert run.returncode == 0, run.stdout + run.stderr
        assert json.loads(run.stdout)['joins'] == joins
        with Image.open(output) as saved:
            assert saved.tobytes() == result.tobytes()
        print(json.dumps({'temporary_files': [dict(path=str(path),
              sha256=hashlib.sha256(path.read_bytes()).hexdigest(), result='pixel and CLI checks passed')
              for path in [*paths, output]]}))
    # Субпиксельное сглаживание меняет пиксели, но не содержание перекрытия.
    with content.crop((0, 300, 160, 800)) as first, content.crop((0, 301, 160, 801)) as second:
        aliased = Image.blend(first, second, .1)
    next_frame = make_frame(0, 500, aliased)
    rendered, rendered_joins = stitch([frames[0], next_frame], 40, 10, 150)
    assert rendered_joins[0]['shift'] == 300
    assert rendered.size == (160, 840)
    with rendered.crop((0, 0, 160, 140)) as top, content.crop((0, 0, 160, 100)) as expected:
        assert top.tobytes() == header.tobytes() + expected.tobytes()
    with rendered.crop((0, rendered.height - 200, 160, rendered.height)) as bottom, aliased.crop((0, 300, 160, 500)) as expected:
        assert bottom.tobytes() == expected.tobytes()
    unrelated = Image.frombytes('RGB', (160, 540), rng.randbytes(540 * 160 * 3))
    for bad in ([frames[0], unrelated],
                [Image.new('RGB', (160, 540), 'white')] * 2,
                [Image.new('RGB', (160, 300))],
                [frames[0], Image.new('RGB', (150, 540))]):
        try:
            stitch(bad, 40, 10, 150)
        except ValueError:
            pass
        else:
            raise AssertionError('Неподходящие кадры ошибочно приняты')
    # All residues of the sampling stride, including one-pixel-wide match areas.
    for width in range(1, 14):
        for height in range(1, 10):
            with sample(content, 7, height, 3, 3 + width) as grid:
                expected = bytes(v for y in range(7, 7 + height, 2)
                                 for x in range(3, 3 + width, 4) for v in content.getpixel((x, y)))
                assert grid.tobytes() == expected
    for image in [*frames, result, from_paths, rendered, aliased, next_frame, unrelated, header, content]:
        image.close()
    print('OK: исходное содержание без пропусков/повторов, один заголовок, чужой кадр отклонён')


if __name__ == '__main__':
    check()
