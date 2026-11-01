// Renders the Murmel logo (rounded square + sound bars) to assets/icon.png without dependencies.
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const SIZE = 256;
const BG = [24, 24, 24];
const BAR = [255, 255, 255];
const BARS = [0.34, 0.62, 0.9, 0.5]; // relative heights
const RADIUS = 56;

function insideRoundRect(x, y, x0, y0, x1, y1, r) {
  const cx = Math.min(Math.max(x, x0 + r), x1 - r);
  const cy = Math.min(Math.max(y, y0 + r), y1 - r);
  return (x - cx) ** 2 + (y - cy) ** 2 <= r * r;
}

const px = Buffer.alloc(SIZE * SIZE * 4);
const barW = 26;
const gap = 18;
const total = BARS.length * barW + (BARS.length - 1) * gap;
const left = (SIZE - total) / 2;
for (let y = 0; y < SIZE; y++) {
  for (let x = 0; x < SIZE; x++) {
    const i = (y * SIZE + x) * 4;
    if (!insideRoundRect(x + 0.5, y + 0.5, 0, 0, SIZE, SIZE, RADIUS)) continue;
    let color = BG;
    BARS.forEach((h, b) => {
      const bx0 = left + b * (barW + gap);
      const bh = h * 150;
      const by0 = (SIZE - bh) / 2;
      if (insideRoundRect(x + 0.5, y + 0.5, bx0, by0, bx0 + barW, by0 + bh, barW / 2)) color = BAR;
    });
    px.set([...color, 255], i);
  }
}

const raw = Buffer.alloc((SIZE * 4 + 1) * SIZE);
for (let y = 0; y < SIZE; y++) px.copy(raw, y * (SIZE * 4 + 1) + 1, y * SIZE * 4, (y + 1) * SIZE * 4);

const crcTable = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
const crc = (buf) => buf.reduce((c, b) => crcTable[(c ^ b) & 0xff] ^ (c >>> 8), 0xffffffff) ^ 0xffffffff;
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type), data]);
  const c = Buffer.alloc(4); c.writeUInt32BE(crc(body) >>> 0);
  return Buffer.concat([len, body, c]);
}
const ihdr = Buffer.alloc(13);
ihdr.writeUInt32BE(SIZE, 0); ihdr.writeUInt32BE(SIZE, 4);
ihdr.set([8, 6, 0, 0, 0], 8);
const png = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0)),
]);
const out = path.join(__dirname, '..', 'assets', 'icon.png');
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, png);
process.stdout.write(`wrote ${out}\n`);
