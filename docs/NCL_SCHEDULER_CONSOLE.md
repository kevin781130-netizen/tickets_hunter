# NCL OPEN LAB 預約控制台（排程版，Mac／Windows 共用）

範圍：`feat/ncl-openlab-booking` 分支。不更動 `main`，不使用 GitHub Actions，不使用 Docker。
房型與流程設定見 [NCL_MULTI_ROOM.md](NCL_MULTI_ROOM.md)。

## 啟動

| 平台 | 方式 |
|---|---|
| Windows 11 | 雙擊專案根目錄的 `launch_ncl_picker.cmd`（維持原本做法；需要 `.venv`） |
| macOS | 雙擊 `launch_ncl_picker.command`（首次會建立 `.venv` 並安裝固定版本的 `zendriver==0.16.0`）。若 Finder 擋下，終端機執行一次 `chmod +x launch_ncl_picker.command`，並在「系統設定 > 隱私權與安全性」允許開啟 |

兩者啟動同一份 `src/ncl_openlab_picker.py`，預約引擎也是同一份 `src/ncl_openlab_autobook.py`。
需要 Python 3.11 以上（含 Tk）與 Google Chrome。macOS 請用 python.org 安裝版，
或 `brew install python-tk`。Chrome 路徑自動偵測；偵測不到時可設環境變數 `NCL_CHROME_PATH`。

## 操作流程

1. 選**房型／設備**、**日期**、**一或兩個時段**（點選順序即預約順序）。
2. 設定**自動開始預約的時間**（台北時間，精確到秒）。預設為「預約日前 7 日 00:00:00」，
   可直接改日期與時間；按「重設為預設」還原。也可切成「立即執行」。
3. 勾選「我明確授權正式送出預約」；選到尚未實機驗證的設備時，另需勾選「我了解此設備尚未實機驗證」。
4. 按「啟動排程」並確認。程式開啟 Chrome：**你自己登入國圖**，
   再按「我已登入，開始待命」。
5. 畫面顯示倒數。到指定時間，引擎才開始執行既有流程：準點刷新、選日期／房型／時段、
   下一步、最後只點一次「預約」，並以網站成功頁核對結果。

狀態：啟動瀏覽器中、等待登入、待命中（倒數）、執行預約中、預約成功（已核對）、
預約失敗／未送出、結果未知（請至官網核對，勿重送）、已取消、流程結束（未預約）、程序異常結束。
視窗下方有本次執行紀錄與歷史紀錄（`ncl_reports/ncl_run_history.jsonl`）。

**取消**只在「啟動中／登入中／待命中」有效；預約一旦開始（執行中）不可取消，也不會重複送出。
執行中關閉視窗會被擋下。**同一時間只允許一個預約程序**（跨視窗、跨終端機的鎖檔，
程序死亡後鎖自動失效）。不保證搶到；實際結果以網站確認為準。

## 時間處理

- 一律使用 Asia/Taipei（UTC+8，無日光節約）。啟動時間可輸入含時區的 ISO 8601，
  例如 `2026-11-05T00:00:00+08:00`、`...Z`；不含時區視為台北時間；純日期（沒有時間）會被拒絕。
- 排程與原本的午夜機制是**同一套邏輯**：預設啟動時間就是原本的放位時間，
  同樣在 T-10 秒預刷新一次、T 準點刷新一次，之後進入既有的有界重試。`--now` 仍代表立即執行。
- 啟動時間不可已過、不可晚於預約日、不可離現在超過 24 小時。提前很久啟動沒有問題
  （原午夜預設路徑仍保留 15 分鐘窗口）；等待時每秒檢查一次，可被取消。
- **系統時間誤差**：勾選「啟動前以網路時間校正」（`--sync-clock`）會以 SNTP 量測誤差並自動校正排程；
  失敗只提示，改用系統時間。也可用 `--clock-offset 秒` 手動校正（±600 秒內）。
- **睡眠／錯過時間**：每秒比對牆上時鐘，發現跳動會記錄；醒來後若已超過預定時間 30 秒，
  回報 `RUN_AT_MISSED`，**不補送**。網路斷線、登入失效會在 T-10 預刷新或 T 準點刷新時
  顯示為 `PRE_REFRESH_BLOCKED_*` / `RELEASE_REFRESH_BLOCKED_*`，同樣不預約。
- 送出後結果不明（`SUBMITTED_SUCCESS_UNVERIFIED` 等）一律顯示「結果未知」，不重送。

## 命令列（GUI 就是用這些參數啟動引擎）

```bash
python src/ncl_openlab_autobook.py --date 2026-11-12 --room p03 --slots 13:00-14:00,14:00-15:00 \
    --reserve-two --auto-submit --run-at 2026-11-05T00:00:00+08:00 --sync-clock
```

| 參數 | 作用 |
|---|---|
| `--run-at ISO8601` | 自訂開始預約時間；與 `--now` 互斥；不可與 `--dry-run` 併用 |
| `--clock-offset SEC` / `--sync-clock` | 手動／自動校正系統時鐘（二擇一） |
| `--machine-status` | 供前端使用：輸出 `@@NCL {...}` 狀態行，待命時接受 stdin 的 `CANCEL` |
| `--plan-only` | 只印出計畫（含 `start_at`），不開瀏覽器 |

未指定 `--run-at` 與 `--now` 時，行為與先前完全相同（目標日前 7 日 00:00，須在 15 分鐘內啟動）。

## 設備（實機盤點草稿）

依 `ncl_reports/ncl_inventory_20261104_144349.json` 建立：縫紉機01–08、刺繡機01，
共用既有 `hourly_slot` 流程（`.time-box[data-param1]`，09:00–20:00 共 11 個一小時時段）。
全部標為 `NOT_VERIFIED` 且 `submit_requires_ack`，**沒有任何一台標成 `LIVE_VERIFIED`**，
設定中沒有 `TODO`。未知事實的處理方式：

- 現況頁類別名未觀察到 → `entry_label: null`，引擎不猜大廳方塊，改由你手動開到日期頁
  （仍可登入後待命）。
- 最後確認頁用字未觀察到 → 以「設備名 + `(?!\d)`」比對，不符就不送出（`SUMMARY_MISMATCH`）。
  這個比對是推測；若實機確認頁不顯示設備名，會在送出前停下，不會誤送。
- 只有縫紉機01 看到時段；其他設備沿用同一份時段，實機未驗證。

## Mac 啟動與結束清理（讀 zendriver 0.16.0 原始碼的發現）

- zendriver 以 PIPE 啟動 Chrome 卻不再讀取 stdout/stderr，長時間待命會塞滿管線使 Chrome 卡住
  → 啟動後以背景執行緒排空管線（測試證明不排空時子程序會被擋住）。
- 其 Chrome 尋找程式用 `os.environ["PATH"]`，漏掉 `~/Applications` 等位置 → 自行偵測
  （環境變數 > 標準路徑 > PATH），指定的路徑不存在時明確報錯而非默默改用別的。
- macOS 關掉最後一個視窗後 Chrome 程序仍常駐、暫存設定檔殘留 → 偵測到使用者關閉所有視窗後
  才停止程序並刪除 zendriver 自建的暫存設定檔（只刪暫存目錄下它自己建立的）；
  取消排程時立即關閉；結果頁顯示期間絕不關閉。
- **這些是依原始碼與模擬測試的修正，沒有在實體 Mac 上跑過（NOT_RUN）。**

## 測試

```bash
python -m unittest discover -s tests -p "test_ncl_openlab_*.py"
python tests/run_ncl_offline_report.py        # 逐項 PASS／FAIL／NOT_VERIFIED 報告
xvfb-run -a python3.12 -m unittest tests.test_ncl_openlab_picker_gui   # Linux 上跑真實 Tk 視窗
```

| 測試檔 | 內容 |
|---|---|
| `test_ncl_openlab_schedule` | 時間解析、倒數、Fake Clock 的準點觸發、提前 2 小時啟動、跨日、已過期、睡眠跳動、取消、網路／登入失效、SNTP |
| `test_ncl_openlab_control` | 狀態協定、單一執行鎖（含真實雙程序）、監督器（真實子行程）：取消、重複啟動、未知結果、引擎中途死亡 |
| `test_ncl_openlab_e2e_schedule` | GUI 參數組裝 → 監督器 → **真實引擎**＋假瀏覽器，真實時鐘：證明準點才開始實際操作、不提前、雙時段、單次送出 |
| `test_ncl_openlab_picker_gui` | 真實 Tk 視窗：預設與自訂時間、驗證、授權、鎖定、取消、關閉保護、倒數與狀態 |
| `test_ncl_openlab_browser` | 三平台 Chrome 偵測、管線排空、清理、引擎的關閉順序 |
| `test_ncl_openlab_platform` | `.cmd`／`.command`、無單一 OS 閘門、各平台啟動參數（模擬） |
| 既有測試 | 房型矩陣（11 個房型）、與凍結舊版逐項比對、引擎、診斷、盤點 |

最近一次完整結果（`tests/run_ncl_offline_report.py`）：

| 環境 | 結果 |
|---|---|
| Python 3.12 + xvfb（有 Tk，真實視窗） | **376 PASS**、0 FAIL、0 略過 |
| Python 3.13（無 Tk） | **360 PASS**、0 FAIL、**16 NOT_VERIFIED**（GUI 測試未執行） |
| macOS 實機、Windows 11 實機 | **NOT_RUN** |

沒有真實執行的測試不標 PASS：缺少 Tk／瀏覽器環境而略過者在報告中記為 `NOT_VERIFIED`。
另以故意破壞排程邏輯做變異驗證（提前開火、移除錯過檢查、忽略自訂時間、放寬房名比對等），測試都能抓到。

## 仍需實機驗證的最少項目

1. **Mac 實機**：雙擊 `.command` → 視窗開啟 → Chrome 偵測 → 登入 → 待命 → 關閉視窗後 Chrome 程序與暫存目錄是否清掉（NOT_RUN）。
2. **Windows 實機**：`.cmd` 啟動、無多餘主控台視窗、高 DPI 版面（NOT_RUN）。
3. **真站不送出的演練**：用 P03（已實機驗證）選一個已開放的日期，用 `--run-at`（現在 + 1 分鐘）且**不加授權**
   （預覽模式，停在最後確認前），確認準點刷新與選取動作。
4. **設備確認頁用字**：對任一台設備實機走到最後確認頁，確認頁是否顯示設備名；之後才可考慮改為 `LIVE_VERIFIED`。
5. 睡眠／喚醒與斷網在真機的實際行為。
