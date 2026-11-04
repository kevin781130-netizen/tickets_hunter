# Tickets Hunter × 國圖：共用程式抽取第一刀

## 目的與安全界線

從固定 RC `release/ncl-openlab-rc-20261104`（commit `4d0da477d52671948181389d3cadb0ba42585d4d`）
建立 `refactor/shared-booking-core-20261104`，**不修改 RC 或 main**。
這刀只抽取**純時間運算與被動瀏覽器結束偵測**，不更改國圖網站操作或最後送出動作。

## 已完成的共用功能

| 原先位置 | 共用位置 | 原國圖呼叫行為 |
|---|---|---|
| `ncl_openlab_autobook.release_time` | `reservation_common.release_datetime` | 保留名稱與 7 天前台北午夜規則 |
| `ncl_openlab_autobook.seconds_until_release` | `reservation_common.seconds_until` | 保留時區轉換與剩餘秒數 |
| `book_with_bounded_retries` 的時間預算比較 | `reservation_common.has_retry_budget` | 保留 3–30 秒／0–180 秒界線，只有預送出狀態可重試 |
| `ncl_openlab_picker_model.release_datetime` | `reservation_common.release_datetime` | GUI 和搶位主流程由同一個純函式計算 |
| `ncl_openlab_autobook.wait_until_browser_manually_closed` | `reservation_browser.wait_until_browser_manually_closed` | 結果頁保留；使用者關閉 Chrome 後程式結束 |

`reservation_common.py`、`reservation_browser.py` 不依賴國圖 DOM、官方網站、
任何其他平台、網路或帳號資料，因此後續其他平台可以重用。

## 刻意不抽取（網站專屬，保留 RC 行為）

- 國圖 `.date-box`、`.space-box1`、`.time-box2`、P03 一小時時段。
- `#gobook` 最後確認、`ZENDRIVER_KEYBOARD_SPACE` 單次送出防重試。
- 台北午夜 **7 天前、T-10、T=0**，限時重試 **90 秒／3 秒** 等政策設定。
- 真實登入、同意條款、成功頁判斷與兩筆連續預約的 fail-closed 流程。

註：時間與重試的**演算法**可以共用，政策值與網頁 DOM 必須留在對應平台。

## 與原生 Tickets Hunter 的關係

原專案已有 `src/nodriver_common.py`、`src/util.py`、`src/settings.py`、
`src/nodriver_tixcraft.py` 以及 `src/platforms/*.py` 的分層設計。
已核對 `util.py`，沒有可直接替代的相同「提前 N 日午夜放位」純函式，
因此先獨立建立可測試、零新相依套件的共用模組。

**本刀尚未把國圖註冊進 Tickets Hunter 主迴圈／既有 Web 設定頁。**
這是保留已實機可用的國圖搶位程序、不引入路由重入風險的刻意分階段選擇。
接入前應先建立 `platforms/ncl_openlab.py` 的 Adapter，明確區分平台路由、
單筆提交、結果不明的禁止重試規則，再做對照測試。

## 本機離線 Gate（不送出預約）

```powershell
git fetch origin
git switch refactor/shared-booking-core-20261104
git pull --ff-only
powershell -NoProfile -ExecutionPolicy Bypass -File .\verify_shared_core.ps1
```

成功標記 `NCL_SHARED_CORE_GATE_PASS`；驗證共用模組編譯與既有國圖
回歸測試。這不等於午夜兩筆的實際預約成功，也不會開 Chrome。
舊的 `verify_ncl_release.ps1` 專屬已封版分支，不應用來測試本整合支線。
