from io import BytesIO
from pathlib import Path
from struct import unpack_from
from PIL import Image, ImageDraw


def first_frame(packet):
    size = unpack_from('<I', packet)[0]
    assert size == len(packet)
    marker = packet[4]
    cursor = 5
    data = bytearray()
    while len(data) < 77882:
        value = packet[cursor]
        cursor += 1
        if value != marker:
            data.append(value)
            continue
        count = packet[cursor]
        cursor += 1
        if count == 0:
            data.append(marker)
            continue
        assert count >= 5
        distance = unpack_from('<H', packet, cursor)[0] + 1
        cursor += 2
        for _ in range(count):
            data.append(data[-distance] if distance <= len(data) else 0)
    assert data[4:6] == b'BM'
    return Image.open(BytesIO(data[4:77882])).convert('RGB')


if __name__ == '__main__':
    output = Path(__file__).parent / 'movie-samples'
    output.mkdir(exist_ok=True)
    for source in sorted(Path(r'D:\Games\FQ4\DATA').glob('movie*.pak')):
        content = source.read_bytes()
        count = unpack_from('<I', content)[0]
        lengths = unpack_from(f'<{count}I', content, 4)
        offset = 4 * (count + 1) + lengths[0]
        panel = Image.new('RGB', (180 * 5, 151 * ((count - 2) // 5 + 1)))
        draw = ImageDraw.Draw(panel)
        for index, length in enumerate(lengths[1:]):
            frame = first_frame(content[offset:offset+length])
            offset += length
            frame.thumbnail((180, 135))
            point = (index % 5 * 180, index // 5 * 151)
            draw.text(point, str(index + 1))
            panel.paste(frame, (point[0], point[1] + 16))
        assert offset == len(content)
        panel.save(output / f'{source.stem}.jpg')
