"""Проверка: один заголовок, точный исходный контент и отказ для чужого кадра."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image
from stitch_post_screenshots import stitch


def check():
    rng = np.random.default_rng(42)
    header = np.full((40, 160, 3), 230, dtype=np.uint8)
    content = rng.integers(0, 256, (1100, 160, 3), dtype=np.uint8)
    frames = [Image.fromarray(np.concatenate((header, content[start:start+500])))
              for start in (0, 300, 600)]
    result, joins = stitch(frames, 40, 10, 150)
    assert np.array_equal(np.asarray(result), np.concatenate((header, content)))
    assert [j['overlap'] for j in joins] == [200, 200]
    for starts, heights in (((0,), (500,)),
                            ((0, 50, 100, 150), (500, 500, 500, 500)),
                            ((0, 200, 400), (600, 500, 650))):
        varied = [Image.fromarray(np.concatenate((header, content[start:start + height])))
                  for start, height in zip(starts, heights)]
        combined, _ = stitch(images=varied, header=40, left=10, right=150)
        expected = np.concatenate((header, content[:starts[-1] + heights[-1]]))
        assert np.array_equal(np.asarray(combined), expected)
        assert all(frame.getpixel((0, 0)) == (230, 230, 230) for frame in varied)
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
    aliased = (0.9 * content[300:800] + 0.1 * content[301:801]).astype(np.uint8)
    next_frame = Image.fromarray(np.concatenate((header, aliased)))
    rendered, rendered_joins = stitch([frames[0], next_frame], 40, 10, 150)
    assert rendered_joins[0]['shift'] == 300
    assert rendered.size == (160, 840)
    assert np.array_equal(np.asarray(rendered)[:140], np.concatenate((header, content[:100])))
    assert np.array_equal(np.asarray(rendered)[-200:], aliased[-200:])
    unrelated = Image.fromarray(rng.integers(0, 256, (540, 160, 3), dtype=np.uint8))
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
    print('OK: исходное содержание без пропусков/повторов, один заголовок, чужой кадр отклонён')


if __name__ == '__main__':
    check()
