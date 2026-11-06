// Writes H.264 video and AAC sound into an MP4 file, a piece at a time, so a recording survives even if the app closes.
const MP4_VIDEO = 1, MP4_AUDIO = 2, MP4_VIDEO_SCALE = 90000;

function mp4Bytes(parts) {
  const flat = parts.flat(Infinity);
  let size = 0;
  for (const p of flat) size += typeof p === 'number' ? 1 : p.length;
  const out = new Uint8Array(size);
  let at = 0;
  for (const p of flat) {
    if (typeof p === 'number') out[at++] = p;
    else { out.set(p, at); at += p.length; }
  }
  return out;
}
const mp4U16 = n => [n >>> 8 & 255, n & 255];
const mp4U32 = n => [n >>> 24 & 255, n >>> 16 & 255, n >>> 8 & 255, n & 255];
const mp4U64 = n => [...mp4U32(Math.floor(n / 2 ** 32)), ...mp4U32(n % 2 ** 32)];
const mp4Text = s => [...s].map(c => c.charCodeAt(0));
const mp4Box = (type, ...parts) => {
  const body = mp4Bytes(parts);
  return mp4Bytes([mp4U32(body.length + 8), mp4Text(type), body]);
};
const mp4Full = (type, version, flags, ...parts) => mp4Box(type, version, flags >>> 16 & 255, flags >>> 8 & 255, flags & 255, ...parts);
const mp4Zeros = n => new Array(n).fill(0);
const MP4_MATRIX = [0, 1, 0, 0, ...mp4Zeros(12), 0, 1, 0, 0, ...mp4Zeros(12), 0x40, 0, 0, 0];

class Mp4Mux {
  constructor(write, width, height, sampleRate, channels) {
    Object.assign(this, { write, width, height, sampleRate, channels });
    this.video = [];
    this.audio = [];
    this.avcC = null;
    this.asc = null;
    this.piece = 0;
    this.lastDuration = 3000;
  }
  addVideo(chunk, meta, time) {                         // time: microseconds since the recording's start
    const raw = new Uint8Array(chunk.byteLength);
    chunk.copyTo(raw);
    let data = raw;
    if (meta && meta.decoderConfig && meta.decoderConfig.description) this.avcC = new Uint8Array(meta.decoderConfig.description.slice(0));
    else if (raw[0] === 0 && raw[1] === 0 && (raw[2] === 1 || (raw[2] === 0 && raw[3] === 1))) data = this.fromStartCodes(raw);
    const key = chunk.type === 'key';
    if (key && this.video.length && time - this.video[0].time >= 1e6) this.flush(time);
    this.video.push({ time, data, key });
  }
  // Graphics cards may give the raw stream, where parts are split by 00 00 01 marks and the setup is mixed in.
  // MP4 wants each part to start with its length, and the setup (SPS and PPS) in the file's header.
  fromStartCodes(raw) {
    const parts = [];
    let start = -1;
    for (let i = 0; i + 2 < raw.length; i++) {
      if (raw[i] || raw[i + 1] || raw[i + 2] !== 1) continue;
      if (start >= 0) parts.push(raw.subarray(start, raw[i - 1] === 0 ? i - 1 : i));
      start = i + 3;
      i += 2;
    }
    if (start >= 0) parts.push(raw.subarray(start));
    const kept = [];
    for (const p of parts) {
      const kind = p[0] & 31;
      if (kind === 7) this.sps = p;
      else if (kind === 8) this.pps = p;
      else if (kind !== 9) kept.push(mp4U32(p.length), p);    // 9 only marks where a picture starts
    }
    if (!this.avcC && this.sps && this.pps) {
      this.avcC = mp4Bytes([1, this.sps[1], this.sps[2], this.sps[3], 0xff, 0xe1, mp4U16(this.sps.length), this.sps, 1, mp4U16(this.pps.length), this.pps]);
    }
    return mp4Bytes(kept);
  }
  addAudio(chunk, meta, time) {
    if (meta && meta.decoderConfig && meta.decoderConfig.description) this.asc = new Uint8Array(meta.decoderConfig.description.slice(0));
    const data = new Uint8Array(chunk.byteLength);
    chunk.copyTo(data);
    this.audio.push({ time, data, duration: chunk.duration || 1024 / this.sampleRate * 1e6 });
  }
  header() {
    const { width: w, height: h, sampleRate: sr, channels: ch } = this;
    // AAC-LC's own description of the sound, if the encoder hasn't given one yet
    const srIndex = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000].indexOf(sr);
    const asc = this.asc || [2 << 3 | srIndex >> 1, (srIndex & 1) << 7 | ch << 3];
    const table = name => mp4Full(name, 0, 0, mp4U32(0));
    const stbl = entry => mp4Box('stbl', mp4Full('stsd', 0, 0, mp4U32(1), entry), table('stts'), table('stsc'), mp4Full('stsz', 0, 0, mp4U32(0), mp4U32(0)), table('stco'));
    const dinf = mp4Box('dinf', mp4Full('dref', 0, 0, mp4U32(1), mp4Full('url ', 0, 1)));
    const mdia = (scale, handler, name, media) => mp4Box('mdia',
      mp4Full('mdhd', 0, 0, mp4U32(0), mp4U32(0), mp4U32(scale), mp4U32(0), mp4U16(0x55c4), mp4U16(0)),
      mp4Full('hdlr', 0, 0, mp4U32(0), mp4Text(handler), mp4Zeros(12), mp4Text(name), 0),
      mp4Box('minf', media, dinf));
    const tkhd = (id, volume, tw, th) => mp4Full('tkhd', 0, 3, mp4U32(0), mp4U32(0), mp4U32(id), mp4U32(0), mp4U32(0), mp4Zeros(8), mp4U16(0), mp4U16(0), mp4U16(volume), mp4U16(0), MP4_MATRIX, mp4U16(tw), mp4U16(0), mp4U16(th), mp4U16(0));
    const avc1 = mp4Box('avc1', mp4Zeros(6), mp4U16(1), mp4Zeros(16), mp4U16(w), mp4U16(h), mp4U32(0x480000), mp4U32(0x480000), mp4U32(0), mp4U16(1), mp4Zeros(32), mp4U16(24), mp4U16(0xffff), mp4Box('avcC', this.avcC));
    const decoder = [0x40, 0x15, 0, 0, 0, mp4U32(0), mp4U32(0), 5, asc.length, asc];
    const es = [mp4U16(MP4_AUDIO), 0, 4, decoder.flat(Infinity).reduce((n, x) => n + (typeof x === 'number' ? 1 : x.length), 0), decoder, 6, 1, 2];
    const esLength = es.flat(Infinity).reduce((n, x) => n + (typeof x === 'number' ? 1 : x.length), 0);
    const mp4a = mp4Box('mp4a', mp4Zeros(6), mp4U16(1), mp4Zeros(8), mp4U16(ch), mp4U16(16), mp4Zeros(4), mp4U16(sr), mp4U16(0), mp4Full('esds', 0, 0, 3, esLength, es));
    const trex = id => mp4Full('trex', 0, 0, mp4U32(id), mp4U32(1), mp4U32(0), mp4U32(0), mp4U32(0));
    return mp4Bytes([
      mp4Box('ftyp', mp4Text('isom'), mp4U32(512), mp4Text('isom'), mp4Text('iso6'), mp4Text('avc1'), mp4Text('mp41')),
      mp4Box('moov',
        mp4Full('mvhd', 0, 0, mp4U32(0), mp4U32(0), mp4U32(1000), mp4U32(0), mp4U32(0x10000), mp4U16(0x100), mp4Zeros(10), MP4_MATRIX, mp4Zeros(24), mp4U32(3)),
        mp4Box('trak', tkhd(MP4_VIDEO, 0, w, h), mdia(MP4_VIDEO_SCALE, 'vide', 'Video', [mp4Full('vmhd', 0, 1, mp4Zeros(8)), stbl(avc1)])),
        mp4Box('trak', tkhd(MP4_AUDIO, 0x100, 0, 0), mdia(sr, 'soun', 'Sound', [mp4Full('smhd', 0, 0, mp4Zeros(4)), stbl(mp4a)])),
        mp4Box('mvex', trex(MP4_VIDEO), trex(MP4_AUDIO))),
    ]);
  }
  flush(nextVideoTime) {
    const video = this.video, audio = this.audio;
    if (!video.length || !this.avcC) return;
    if (!this.piece) this.write(this.header());
    this.video = [];
    this.audio = [];
    const inScale = (t, scale) => Math.round(t * scale / 1e6);
    const vRows = video.map((s, i) => {
      const next = i + 1 < video.length ? video[i + 1].time : nextVideoTime;
      const duration = next === undefined ? this.lastDuration : inScale(next, MP4_VIDEO_SCALE) - inScale(s.time, MP4_VIDEO_SCALE);
      this.lastDuration = duration;
      return [mp4U32(duration), mp4U32(s.data.length), mp4U32(s.key ? 0x02000000 : 0x01010000)];
    });
    const aRows = audio.map(s => [mp4U32(inScale(s.duration, this.sampleRate)), mp4U32(s.data.length)]);
    const traf = (id, start, flags, count, offset, rows) => mp4Box('traf',
      mp4Full('tfhd', 0, 0x020000, mp4U32(id)),
      mp4Full('tfdt', 1, 0, mp4U64(start)),
      mp4Full('trun', 0, flags, mp4U32(count), mp4U32(offset), rows));
    const moof = (vAt, aAt) => mp4Box('moof',
      mp4Full('mfhd', 0, 0, mp4U32(++this.piece)),
      traf(MP4_VIDEO, inScale(video[0].time, MP4_VIDEO_SCALE), 0x701, video.length, vAt, vRows),
      audio.length ? traf(MP4_AUDIO, inScale(audio[0].time, this.sampleRate), 0x301, audio.length, aAt, aRows) : []);
    const size = moof(0, 0).length;
    this.piece--;
    const vBytes = video.reduce((n, s) => n + s.data.length, 0);
    const start = size + 8;
    this.write(mp4Bytes([moof(start, start + vBytes), mp4U32(8 + vBytes + audio.reduce((n, s) => n + s.data.length, 0)), mp4Text('mdat'), video.map(s => s.data), audio.map(s => s.data)]));
  }
}
