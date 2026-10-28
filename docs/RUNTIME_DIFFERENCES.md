# ความต่างข้าม runtime (Runtime migration — รายการ B) ที่ต้องตรวจรับก่อน production

สถานะ: **pending — ยังไม่มีผู้ตรวจรับ** · สร้าง 9 ต.ค. 2026 (+07:00) โดย ทีมพัฒนา (self-check) · ต้องอัปเดตเมื่อมี runtime ใหม่ (เช่น VM จริง)

## เกณฑ์ที่ใช้ (ผู้ใช้ตัดสิน 9 ต.ค. 2026)

- **A. Refactor parity** — โค้ดต้นฉบับ (repo เพื่อน `e6aee03`) กับโค้ดที่ refactor ต้องให้ผลตรงทุกบิต เมื่อใช้ข้อมูล ตัวเลือก และ runtime เดียวกัน (image/build, architecture, เครื่อง, library versions/builds, seed และการตั้งค่าที่มีผลต่อการคำนวณ) ไม่มี tolerance — ตรวจด้วย `compare_runs.py` / `ui_compare.py` ภายในชุด reference ของ runtime นั้น
- **B. Runtime migration** — ความต่างระหว่าง runtime (Mac ↔ Linux ↔ VM) ไม่ใช่ผลผ่าน/ตกของ refactor แต่เป็นรายการในเอกสารนี้ที่ต้องมีผู้ตรวจรับก่อนเปิดใช้งานจริง
- การยอมรับเกณฑ์นี้มีไว้เพื่อเดินงาน refactor ต่อ **ไม่ใช่การรับรองว่าผล Linux ถูกต้องทางวิชาการหรือพร้อมใช้งานจริง**
- "Drift ยังเป็นโมเดลที่ดีที่สุด" ไม่ใช่เหตุให้ละความต่างอื่นในเอกสารนี้

## Runtime ที่มี reference

| ชุด | runtime | reference | สถานะ |
|---|---|---|---|
| `mac-idntwww` | macOS arm64, conda env idntwww (OpenBLAS 0.3.31 build conda target VORTEX) | `docs/baseline/` (ตัวเลข 35 ผล, หน้าจอ 52 สถานะ, runtime.json) | ตรึงแล้ว รันซ้ำตรง |
| `linux-arm64` | `tfp-runtime:arm64` = `sha256:37424b8dfa971dc0313209a49cd916ed67cc4c9742d751300e304e9447de86f4` (python:3.11.15-slim@sha256:90744cff…, Debian glibc 2.41, aarch64, `backend/requirements.lock`, OpenBLAS ของ PyPI `scipy-openblas 0.3.31.188.0` neoversev2) | `docs/baseline/linux-arm64/` | ตรึงแล้ว รันซ้ำตรง (ตัวเลข 28/28, หน้าจอ 16/16) |
| linux/amd64 (จำลองบน Mac) | Rosetta "VirtualApple" + OpenBLAS kernel Haswell (image ทดลอง 1C) | ไม่มี (หลักฐานเบื้องต้นเท่านั้น) | ต้องตรวจบน VM จริงใน Step 9 |

## สาเหตุ (เท่าที่หลักฐานบอกได้)

source, snapshot, seed, ตัวเลือก และเวอร์ชัน package ตรงกันทุกอย่าง แต่ runtime/build ต่างกัน (BLAS/LAPACK และ kernel, compiler, libc/libm, build ของ package) และพบความต่างของผล **ยังไม่ได้แยกทุกสาเหตุ** และการเทียบนี้อย่างเดียว **สรุปไม่ได้ว่า runtime ฝั่งไหนถูก** OLS/ECM ต่างระดับบิตสุดท้าย ส่วน ARIMA (optimizer) ขยายความต่างจนถึงหลักที่แสดงบางจุด

## Mac (`mac-idntwww`) เทียบ Linux arm64 (`linux-arm64`)

ผลดิบ 35 ชุด: ตรง 31 · ต่าง 4 (`holdout`, `rolling`, `sr.pvalues`, `sr_raw_map` — สองชุดหลังต่างที่บิตสุดท้าย ~1e-16 ไม่กระทบค่าที่แสดง)

เทียบ `mac-idntwww` (mac-idntwww) กับ `linux-arm64` (linux-arm64) — ทั้งสองผลตรง reference ของ runtime ตัวเองทุกบิตแล้ว

### order ที่ ARIMA เลือก (ต่าง 0 จาก 41 ครั้ง)

| ส่วน | หน้าต่าง | mac-idntwww | linux-arm64 |
|---|---|---|---|

### convergence และคำเตือนของ fit (ต่าง 11 จาก 41 ครั้ง)

| ส่วน | ปีสุดท้ายที่ฝึก | mac-idntwww: fit ไม่ converge · ตัวที่เลือก | linux-arm64 | หมายเหตุ |
|---|---|---|---|---|
| rolling | 1968 | 7/15 · ตัวที่เลือก converge=False | 8/15 · ตัวที่เลือก converge=True | |
| rolling | 1971 | 2/15 · ตัวที่เลือก converge=True | 1/15 · ตัวที่เลือก converge=True | |
| rolling | 1974 | 9/15 · ตัวที่เลือก converge=False | 8/15 · ตัวที่เลือก converge=False | |
| rolling | 1976 | 8/15 · ตัวที่เลือก converge=False | 9/15 · ตัวที่เลือก converge=False | |
| rolling | 1980 | 4/15 · ตัวที่เลือก converge=True | 3/15 · ตัวที่เลือก converge=True | |
| rolling | 1982 | 6/15 · ตัวที่เลือก converge=False | 4/15 · ตัวที่เลือก converge=True | |
| rolling | 1983 | 2/15 · ตัวที่เลือก converge=True | 1/15 · ตัวที่เลือก converge=True | |
| rolling | 1991 | 9/15 · ตัวที่เลือก converge=False | 7/15 · ตัวที่เลือก converge=True | |
| rolling | 1994 | 8/15 · ตัวที่เลือก converge=True | 8/15 · ตัวที่เลือก converge=False | |
| rolling | 1995 | 8/15 · ตัวที่เลือก converge=True | 7/15 · ตัวที่เลือก converge=True | |
| rolling | 2019 | 5/15 · ตัวที่เลือก converge=True | 4/15 · ตัวที่เลือก converge=True | |

### ค่าทายใน holdout: ต่าง 5 ค่า · ต่างที่ทศนิยม 2 ตำแหน่ง (ที่ตารางแสดง) 2 ค่า

| ส่วน | ปี | โมเดล | mac-idntwww | linux-arm64 |
|---|---|---|---|---|
| holdout | 2020 | ARIMA | 264.85 | 264.84 |
| holdout | 2021 | ARIMA | 267.24 | 267.23 |

### ค่าทายใน rolling: ต่าง 32 ค่า · ต่างที่ทศนิยม 2 ตำแหน่ง (ที่ตารางแสดง) 2 ค่า

| ส่วน | ปี | โมเดล | mac-idntwww | linux-arm64 |
|---|---|---|---|---|
| rolling | 1992 | ARIMA | 195.67 | 195.66 |
| rolling | 2014 | ARIMA | 240.35 | 240.36 |

### ตัวเลขสรุปที่ต่าง (ค่าที่แสดง · ค่าดิบ)

| ส่วน | รายการ | mac-idntwww | linux-arm64 | ค่าดิบ |
|---|---|---|---|---|
| holdout | arima_mape | 3.67 | 3.67 | 3.6699306386338018 / 3.6691825490062877 |
| holdout | arima_rmse | 10.823 | 10.820 | 10.823238560306306 / 10.820235172398496 |
| rolling | arima_mape | 3.50 | 3.50 | 3.5042986037298385 / 3.5042830758824715 |
| rolling | arima_mape_crisis | 3.74 | 3.74 | 3.7401103777965425 / 3.7402187484564204 |
| rolling | arima_mape_normal | 3.49 | 3.49 | 3.4918874577263272 / 3.4918654089048955 |
| rolling | arima_rmse | 9.094 | 9.094 | 9.093689058806763 / 9.09379908154766 |
| rolling | dm_arima_naive.mean_d | 47.42010569826185 | 47.42210673555704 | 47.42010569826185 / 47.42210673555704 |
| rolling | dm_arima_naive.pvalue | 0.092 | 0.092 | 0.09243408111267049 / 0.09242187290729698 |
| rolling | dm_arima_naive.stat | 1.725 | 1.725 | 1.7250610320216826 / 1.7251280535274158 |

### ค่าที่แสดงบนหน้าจอ (AppTest 52 สถานะ ของแอปต้นฉบับในแต่ละ runtime)

หน้าจอที่ต่าง 29 จาก 52 สถานะ: v03_forecast_h5_default, v04_forecast_h3, v04_forecast_h10, v04_forecast_h15, v05_forecast_h5_again, v06_rolling_threshold_min, v06_rolling_threshold_max, v06_rolling_threshold_default, v07_scenario_FDI_GDP_shock1, v07_scenario_FDI_GDP_shock5_0, v07_scenario_FDI_GDP_shockm2_5, v07_scenario_FEE_GDP_shock1, v07_scenario_FEE_GDP_shock5_0, v07_scenario_FEE_GDP_shockm2_5, v07_scenario_ln_HDI_shock1, v07_scenario_ln_HDI_shock5_0, v07_scenario_ln_HDI_shockm2_5, v07_scenario_ln_JOUR_GDP_shock1, v07_scenario_ln_JOUR_GDP_shock5_0, v07_scenario_ln_JOUR_GDP_shockm2_5, v07_scenario_MKTCOM_shock1, v07_scenario_MKTCOM_shock5_0, v07_scenario_MKTCOM_shockm2_5, v12_back_to_forecast, r07_forecast_custom_vars, r12_forecast, r13_scenario_ln_HDI_shock5, r14_scenario_ln_HDI_shock5_set, r17_data_vars

### ข้อความที่แสดงต่างกัน (5 แบบ ไม่นับซ้ำข้ามสถานะ)

| ตัวอย่างสถานะ | ui-baseline | ui-linux-arm64-ref-2 |
|---|---|---|
| v03_forecast_h5_default (+28) | `e7b7422fb85c41cc945bdc69a94b3906` | `120ec4756797e7f780e95ee3c88ce66f` |
| v03_forecast_h5_default (+28) | `: {"view": {"strokeWidth": 0}}, "data": {"name": "e7b7422fb85c41cc945bdc69a94b3906"}, "height": 300,` | `: {"view": {"strokeWidth": 0}}, "data": {"name": "120ec4756797e7f780e95ee3c88ce66f"}, "height": 300,` |
| v03_forecast_h5_default (+28) | `2</td><td>37</td><td>191.27</td><td style="">195.67</td><td style="color:var(--green);font-weight:70` | `2</td><td>37</td><td>191.27</td><td style="">195.66</td><td style="color:var(--green);font-weight:70` |
| v03_forecast_h5_default (+28) | `vy-soft);opacity:0.85;margin-top:2px;">RMSE: 10.823</div></div></div></div>` | `vy-soft);opacity:0.85;margin-top:2px;">RMSE: 10.820</div></div></div></div>` |
| v03_forecast_h5_default (+28) | `<tr><td>2020</td><td>251.09</td><td style="">264.85</td><td style="color:var(--green);font-weight:70` | `<tr><td>2020</td><td>251.09</td><td style="">264.84</td><td style="color:var(--green);font-weight:70` |

### ข้อมูลตาราง/กราฟที่ต่าง (Arrow ที่หน้าเว็บนำไปแสดง)

| องค์ประกอบ | จำนวนค่าที่ต่าง (รวมทุกสถานะ) | จำนวนสถานะ | ตัวอย่าง |
|---|---|---|---|
| `$.elements[35]` | 1102 | 29 | `datasets[0].data.data.values[0][2]`: '0x1.c08cdb4d38145p+1' → '0x1.c08c590b6bb65p+1' |

หมายเหตุ: ตารางข้อความด้านบนแสดงตำแหน่งแรกที่ต่างในแต่ละสตริง ตาราง holdout/rolling มีหลายแถวในสตริงเดียว รายการค่าทายที่แสดงต่างครบอยู่ในหัวข้อ "ค่าทายใน holdout/rolling" ด้านบน (`$.elements[35]` คือข้อมูลของกราฟเกณฑ์จำนวนปีฝึกใน rolling backtest)

## linux/amd64 แบบจำลอง (หลักฐานเบื้องต้นจาก Step 1C)

เทียบ Mac: ผลดิบตรง 17/35 — ค่าของสมการ ECM ต่างระดับบิตสุดท้าย แต่ rolling ARIMA MAPE 3.0379% (Mac 3.5043%), RMSE 8.3487 (Mac 9.0937), Diebold–Mariano ARIMA vs Naive stat 1.3883 p 0.1729 (Mac 1.7251 p 0.0924) และ holdout ARIMA ต่างที่ทศนิยมตำแหน่งที่ 3 — VM จริงอาจใช้ kernel ต่างจากการจำลอง จึงต้องตรึง reference และตรวจบน VM ใน Step 9

## สิ่งที่ต้องมีคนตรวจรับก่อน production

| ข้อ | ผู้ตรวจ | สถานะ |
|---|---|---|
| ความต่างของ ARIMA backtest (ค่าทาย, RMSE, ตาราง/กราฟที่แสดง) ระหว่าง runtime | ผู้รู้โมเดล (เพื่อน/อาจารย์) + ผู้ใช้ | pending |
| convergence ของโมเดลที่ถูกเลือกต่างกันบางหน้าต่าง | ผู้รู้โมเดล | pending |
| ผลบน VM จริง (สถาปัตยกรรม/CPU ของหน่วยงาน) | ผู้ใช้ + IT (Step 9) | pending — ยังไม่มี VM |
| เลือกว่าระบบจริงยึด runtime ไหนเป็นตัวเลขที่เผยแพร่ | ผู้ใช้ + ผู้รู้โมเดล | pending |

ห้ามแก้โมเดลหรือ optimizer เพื่อลดความต่างเป็นงานแถม (งานขอบเขต B ในแผน)

**ผลต่อระบบใหม่ (อัปเดต 9 ต.ค. 2026 18:50):** api/worker ของระบบใหม่รันใน image linux-arm64 จึงแสดงค่าฝั่ง Linux ในตารางนี้
(เช่น holdout 2020 264.84, 2021 267.23, RMSE 10.823 → 10.820) — ภาพหน้าจอ Step 4 (`STEP_04.md` หัวข้อ 5.1) เทียบกับแอปเดิมที่รันบน Mac
จึงต่างที่จุดเหล่านี้ ซึ่งตรงกับที่โค้ดต้นฉบับเองให้บน linux-arm64 (เกณฑ์ A ของระบบใหม่ผ่านบน runtime เดียวกัน); การเลือก runtime ของค่าที่เผยแพร่ยังเป็นแถวสุดท้ายของตารางด้านบน

## หลักฐาน

`private/verification/runtime_diff_mac_vs_linux-arm64.md`, `private/verification/ui_diff_mac_vs_linux-arm64.md`, `private/baseline/runtime_diff_{mac-idntwww,linux-arm64}.json`, `private/baseline/oracle_{mac-runtime-20261009,linux-arm64-ref-1,linux-arm64-ref-2}.json`, `private/baseline/ui/{ui-mac-runtime-20261009,ui-linux-arm64-ref-1,ui-linux-arm64-ref-2}/`, `private/verification/1c-20261009-*/`
คำสั่งสร้างรายงาน: `python -B tools/baseline/runtime_diff.py report mac-idntwww linux-arm64` และ `python -B tools/baseline/runtime_diff.py ui-report ui-baseline ui-linux-arm64-ref-2`

## Source acc64ee — 12 ตุลาคม 2026

Reference ใหม่แยก `docs/baseline/acc64ee-mac-idntwww/` และ `acc64ee-linux-arm64/` จากโค้ดต้นฉบับทั้งคู่บน snapshot เดิม ผล 36 ชุดต่างข้าม runtime 4 ชุด: `sr.pvalues`, `sr_raw_map`, `holdout`, `rolling` อีก 32 ชุดตรงทุกบิต ชื่อ output ไม่ใช่จำนวน scalar ที่ต่าง หลักฐาน `private/verification/src-acc64ee-preservation-r2/report.json` และ oracle_acc64ee-*-1.json ตารางรุ่นก่อนข้างบนยังเป็นประวัติ เกณฑ์ A ใน runtime เดียวกันผ่าน เกณฑ์ B ยังรอผู้รู้โมเดล/ผู้ใช้/IT และต้องตรวจบน VM จริง
