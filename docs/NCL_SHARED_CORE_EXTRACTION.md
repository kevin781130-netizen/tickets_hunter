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

## 第二刀｜國圖獨立 Adapter（未註冊主路由）

- 新增 `src/platforms/ncl_openlab.py`，提供與平台模組一致的
  `nodriver_ncl_main(tab, url, config_dict)` 入口。
- **此入口目前只回報手動模式，絕不選時段、刷新或送出**。
  目前不修改 `src/nodriver_tixcraft.py` URL 分派與 `settings.py`。
- 若由明確授權的呼叫者執行 `nodriver_ncl_booking(..., auto_submit=True)`，
  必須通過日期、房間、時段與國圖官方主機驗證，才將**單筆**
  操作交給已存在的 `ensure_date_grid`／`book_one_target`。
  結果不明原樣回傳，不重送。兩筆模式仍歸原本的獨立控制程式。
- 新增 `tests/test_ncl_openlab_adapter.py` 八項模擬測試；
  `verify_shared_core.ps1` 增加 Adapter 編譯。預期總測試數
  **181**，尚待 Mac 執行結果確認。
- 原本 Windows GUI 與 Mac 離線測試流程不變；
  `main` 與固定 RC 的 SHA 沒有修改。

## 第三刀｜主引擎被動路由

- 在 `src/nodriver_tixcraft.py` 以 `urllib.parse.urlsplit(url).hostname`
  精確辨識 `spms.ncl.edu.tw`，只呼叫 `nodriver_ncl_main`。
- 國圖條件分支以 `continue` 結束，置於主引擎排程刷新與通用
  Cloudflare 動作之前，避免一般售票流程誤操作國圖預約網站。
- **主引擎完全不呼叫 `nodriver_ncl_booking`，不得透過設定值自動送出。**
  原本 `ncl_openlab_autobook.py` 仍是唯一已實機驗證的啟動入口。
- 新增 4 項靜態路由回歸測試與主引擎語法 Gate。
- macOS 前一版 181 項離線測試已由使用者確認 PASS；
  本刀完成後預期 185 項，**待 Mac 執行確認**。

`main` 和固定的 `release/ncl-openlab-rc-20261104` 不修改。

## 第四刀｜唯讀檢查結束保留 Chrome

- `src/ncl_openlab_probe.py` 的 `finally` 不再呼叫 `browser.stop()`。
  改為共用的 `wait_until_browser_manually_closed(browser)`，無論檢查成功
  或發生錯誤，都將原本的 Chrome 畫面留給使用者核對；
  使用者自行關閉 Chrome 後，終端機程序才會結束。
- 這個被動等待只查詢本機 DevTools 目標，不會刷新國圖網站、
  登入、點擊選位、發送預約或自動提交。
- `tests/test_ncl_openlab_probe_lifecycle.py` 新增兩項離線測試，
  確認檢查成功及遇到錯誤時都沒有呼叫 `browser.stop()`。
- 上一版 Mac 185 項已由使用者確認 PASS；本刀預期 187 項，
  **尚待 Mac 重新測試**。
- **唯讀檢查不代表實際預約成功**；確認訂位應以國圖正式成功頁
  或會員預約紀錄為準。

Mac 離線驗證：

```bash
cd ~/ncl-openlab && git pull --ff-only && .venv/bin/python -m unittest discover -s tests -p "test_ncl_openlab_*.py" -q
```

驗證唯讀工具實際保留 Chrome（須自行登入，無自動預約）：

```bash
cd ~/ncl-openlab && .venv/bin/python src/ncl_openlab_probe.py
```

## 第五刀｜沿用原 Tkinter 面板，接通 macOS Terminal

- `src/ncl_openlab_picker.py` 的「確認設定並開啟預約瀏覽器」按鈕，
  **不再拒絕 macOS**，仍先透過 `build_booking_args` 檢查日期、
  空間、1–2 個時段與明確送出授權；確認視窗同意後呼叫
  `ncl_openlab_launcher.launch_booking_command`。
- Windows 保留 `subprocess.Popen(..., CREATE_NEW_CONSOLE)` 行為。
  macOS 透過系統 `osascript` 要求 Terminal.app 開啟**獨立互動終端**，
  用目前 Python 直譯器執行原本的 `ncl_openlab_autobook.py`。
  路徑與參數分別以 `shlex.quote / shlex.join` 和 AppleScript
  字串轉義處理，不拼接未驗證的 shell 參數。
- Mac 終端在後端結束後顯示 `NCL_PROCESS_EXIT` 並等待使用者按 Enter，
  避免關閉視窗而看不到結果；Chrome 仍由原後端保留，直到手動關閉。
  Terminal 的啟動成功**不是**預約成功。
- `tests/test_ncl_openlab_picker_mac.py` 新增 7 個離線測試，涵蓋
  路徑轉義、Mac/Windows 分流、平台不支援/啟動失敗，以及真正的 GUI
  按鈕方法到預約後端 CLI 的雙時段授權與未授權拒絕。
- 已有的 GUI 靜態測試改查新啟動器，不再誤認 GUI 檔案內必須直接
  呼叫 Windows-only API。
- 先前 Mac 187 項測試已由使用者確認 PASS，本刀預期 **194 項**，
  **仍待 Mac 實跑確認**。Windows 與 Mac 的 GUI → 瀏覽器 → 官方
  預約成功端到端測試**尚未完成**。
- 此刀未修改 `main`、封版 RC 或 `ncl_openlab_autobook.py`。

Mac 離線 Gate（不打開 UI、不送預約）：

```bash
cd ~/ncl-openlab && git pull --ff-only && .venv/bin/python -m py_compile src/ncl_openlab_picker.py src/ncl_openlab_launcher.py && .venv/bin/python -m unittest discover -s tests -p "test_ncl_openlab_*.py" -q
```

通過後可**單獨**開啟原前端，以確認真正的 Mac GUI：

```bash
cd ~/ncl-openlab && .venv/bin/python src/ncl_openlab_picker.py
```

警告：面板中的「確認設定並開啟預約瀏覽器」在授權後會啟動
真實預約程式；**不要為了 UI 測試按下正式預約確認**。
