// Node.js 22 的本機合成資料串接範例；不是正式 SDK。
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';

const kind = process.argv[2] ?? 'ecg';
if (!['heart-rate', 'ecg'].includes(kind)) throw new Error('使用方式：node upload.mjs ecg 或 heart-rate');
const base = new URL(process.env.CROSS_SANDBOX_URL ?? 'http://127.0.0.1:8002');
if (base.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(base.hostname) || base.username || base.password || base.pathname !== '/' || base.search || base.hash) {
  throw new Error('此範例僅支援 http 的本機 loopback 沙盒 URL');
}
const token = process.env.CROSS_SANDBOX_TOKEN ?? '';
if (token.length < 32 || !/^[\x21-\x7E]+$/.test(token)) throw new Error('請以環境變數設定至少 32 個可見 ASCII 字元的沙盒授權碼');
const load = async name => JSON.parse(await readFile(new URL(`../../fixtures/${name}`, import.meta.url), 'utf8'));
const requireMatch = (condition, message) => { if (!condition) throw new Error(message); };

async function send(method, path, body) {
  const response = await fetch(new URL(path, base), {
    method, redirect: 'error', signal: AbortSignal.timeout(10_000),
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (![200, 201].includes(response.status)) throw new Error(`HTTP ${response.status}：請依文件處理，保留原事件，不更換 event_id`);
  return { status: response.status, data: await response.json() };
}

// 以微秒核對含時區時間，避免 Date 的毫秒精度掩蓋差異。
function timestamp(value) {
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  requireMatch(match, '量測時間需含時區，精度最多微秒');
  const millis = Date.parse(match[1] + match[3]);
  requireMatch(Number.isFinite(millis), '量測時間無法解析');
  return BigInt(millis) * 1000n + BigInt((match[2] ?? '').padEnd(6, '0'));
}

async function main() {
  const patient = await load('patient.json');
  const device = await load('device.json');
  for (const [path, body] of [['patients', patient], ['devices', device]]) {
    const response = await send('POST', `/api/v1/${path}`, body);
    requireMatch(isDeepStrictEqual(response.data, body), '登錄回應不一致');
  }
  const payload = await load(`${kind}.json`);
  if (kind === 'ecg') {
    const samples = payload.waveform.samples;
    requireMatch(samples.every(value => Number.isInteger(value) && value >= -100000 && value <= 100000), '樣本需為契約範圍內的有號整數 µV');
    const bytes = Buffer.alloc(samples.length * 4);
    samples.forEach((value, index) => bytes.writeInt32LE(value, index * 4));
    requireMatch(createHash('sha256').update(bytes).digest('hex') === payload.waveform.sample_sha256, '本機樣本校驗碼不符');
  }
  const first = await send('POST', `/api/v1/measurements/${kind}`, payload);
  requireMatch(first.data.duplicate === (first.status === 200), '接收狀態無法確認');
  const retry = await send('POST', `/api/v1/measurements/${kind}`, payload);
  requireMatch(retry.status === 200 && retry.data.duplicate === true && isDeepStrictEqual(retry.data.measurement, first.data.measurement), '原樣重送未去重或回執不一致');
  const record = first.data.measurement;
  requireMatch(typeof record.id === 'string' && record.id.length > 0, '回執缺少伺服器 id');
  for (const field of ['event_id', 'patient_id', 'device_id']) requireMatch(record[field] === payload[field], `回執 ${field} 不一致`);
  requireMatch(timestamp(record.measured_at) === timestamp(payload.measured_at), '回執量測時間不一致');
  requireMatch(record.schema_version === '1.0' && isDeepStrictEqual(record.patient, patient) && isDeepStrictEqual(record.device, device), '契約版本或來源快照不一致');
  if (kind === 'ecg') {
    requireMatch(record.kind === 'ecg' && record.unit === 'uV' && isDeepStrictEqual(record.waveform, payload.waveform), '回執波形不一致');
    requireMatch(record.sample_count === payload.waveform.samples.length && record.duration_ms === payload.waveform.samples.length * 1000 / payload.waveform.sample_rate_hz, '回執樣本數或時間長度不一致');
  } else requireMatch(record.kind === 'heart_rate' && record.unit === '/min' && record.heart_rate === payload.heart_rate, '回執心率不一致');
  const stored = await send('GET', `/api/v1/measurements/${record.id}`);
  requireMatch(isDeepStrictEqual(stored.data, record), '讀回資料不一致；保留原事件待處理');
  console.log(`${kind}：登錄、上傳、原樣重送去重、原生讀回核對完成`);
  console.log(`event_id=${payload.event_id}，伺服器 id=${record.id}`);
}
main().catch(error => { console.error(`串接未完成：${error.message}`); process.exitCode = 1; });
