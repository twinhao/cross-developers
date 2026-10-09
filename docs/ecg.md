# ECG 波形契約

完整請求見 [ecg.json](../fixtures/ecg.json)，共用波形見 [ecg-waveform.json](../fixtures/ecg-waveform.json)。兩個原生 App 與範例客戶端使用同一份合成訊號，沒有取自病人。

`POST /api/v1/measurements/ecg` 沿用量測封套，單位固定 `uV`。waveform 的欄位如下：

| 欄位 | 定義 |
|---|---|
| lead | `I` |
| sample_rate_hz | 整數 50–1000 Hz |
| samples | 有號整數 µV；2–5000 點，每點 −100000 至 100000 |
| sample_sha256 | 64 位小寫十六進位樣本校驗碼 |
| signal_origin | `simulator` |
| calibration | `physical-microvolts` |
| filtering | `none` |

最多 10 秒，樣本數不可大於取樣率 × 10。範例為 500 點／250 Hz，即 2 秒。這是一次完整片段上傳，尚未提供分段、串流或多導程。

## 校驗碼

按原順序將樣本編為 **signed 32-bit little-endian**，串接後計算 SHA-256。不是對 JSON 文字做雜湊；空白與鍵序不影響結果。不可把負數轉為字串、浮點或 unsigned 數值再計算。

Python：

```python
packed = struct.pack(f"<{len(samples)}i", *samples)
checksum = hashlib.sha256(packed).hexdigest()
```

JavaScript：

```javascript
const bytes = Buffer.alloc(samples.length * 4);
samples.forEach((value, index) => bytes.writeInt32LE(value, index * 4));
const checksum = createHash('sha256').update(bytes).digest('hex');
```

本包共用樣本的校驗碼：

```text
42fbe3a8e51583d2a25fd19490e7d7b3f46beb5e54bde7b0dd0cda25aba7ca2b
```

校驗碼驗證樣本完整性；其他中繼資料由事件內容比較保護。它不提供來源身份或簽章。

## 顯示與實機資料

原生 App 直接繪出完整合成樣本，標示導程、Hz、樣本數、秒數及 µV。顯示網格只是示意比例，沒有臨床紙速／增益設定，也不提供自動診斷或從波形推算心率。

本版只接受 simulator，不接受偽標為模擬資料的真實訊號。實機 adapter 需先取得 ADC 轉換至 µV 的校正、導程、實際取樣率、濾波及掉包定義。ADC counts 不能直接當作 µV，不能以補點掩蓋掉包。

## 原生讀回與 FHIR

原生紀錄包含完整 waveform、`sample_count` 與 `duration_ms`。補傳與讀回保留原始樣本；不得為了顯示而改寫保存值。

ECG 的 FHIR 匯出明確回 501。依實際接收方指定的 profile、版本與波形表示方式驗證後，再加入交換 adapter；不把單筆心率的映射直接套用在波形上。
