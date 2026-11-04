# NCL OPEN LAB 預約控制台（排程版，Mac／Windows 共用）

範圍：`feat/ncl-openlab-booking` 分支。不更動 `main`，不使用 GitHub Actions，不使用 Docker。
房型與流程設定見 [NCL_MULTI_ROOM.md](NCL_MULTI_ROOM.md)。

## 啟動

| 平台 | 方式 |
|---|---|
| Windows 11 | 雙擊專案根目錄的 `launch_ncl_picker.cmd`（維持原本做法；需要 `.venv`） |
| macOS | 雙擊 `launch_ncl_picker.command`（首次會建立 `.venv` 並安裝固定版本的 `zendriver==0.16.0`）。若 Finder 擋下，終端機執行一次 `chmod +x launch_ncl_picker.command`，並在「系統設定 > 隱私權與安全性」允許開啟 |

兩者啟動同一份 `src/ncl_openlab_picker.py`，預約引擎也是同一份 `src/ncl_openlab_autobook.py`。
需要 Python 3.11 以上（含 Tk）與 Google Chrome；要使用「安全儲存憑證」另需 `keyring==25.6.0`
（`.command` 首次啟動與 `.cmd` 啟動時會自動安裝固定版本，已列入 `requirement.txt`）。macOS 請用 python.org 安裝版，
或 `brew install python-tk`。Chrome 路徑自動偵測；偵測不到時可設環境變數 `NCL_CHROME_PATH`。

## 操作流程

1. 選**房型／設備**、**日期**、**一或兩個時段**（點選順序即預約順序）。
2. 設定**自動開始預約的時間**（台北時間，精確到秒）。預設為「預約日前 7 日 00:00:00」，
   可直接改日期與時間；按「重設為預設」還原。也可切成「立即執行」。
3. 勾選「我明確授權正式送出預約」；選到尚未實機驗證的設備時，另需勾選「我了解此設備尚未實機驗證」。
4. 按「啟動排程」並確認。程式開啟 Chrome 並**自動檢查登入狀態**：已登入就直接沿用；
   未登入時由**你親自輸入圖片驗證碼並登入**，程式從網站實際狀態確認成功後自動進入待命，
   不需要按任何按鈕（詳見下一節）。
5. 畫面顯示倒數。到指定時間，引擎才開始執行既有流程：準點刷新、選日期／房型／時段、
   下一步、最後只點一次「預約」，並以網站成功頁核對結果。

狀態：啟動瀏覽器中、等待登入、待命中（倒數）、執行預約中、預約成功（已核對）、
預約失敗／未送出、結果未知（請至官網核對，勿重送）、已取消、流程結束（未預約）、程序異常結束。
視窗下方有本次執行紀錄與歷史紀錄（`ncl_reports/ncl_run_history.jsonl`）。

**取消**只在「啟動中／登入中／待命中」有效；預約一旦開始（執行中）不可取消，也不會重複送出。
執行中關閉視窗會被擋下。**同一時間只允許一個預約程序**（跨視窗、跨終端機的鎖檔，
程序死亡後鎖自動失效）。不保證搶到；實際結果以網站確認為準。

## 登入與 Session（驗證碼永遠由你輸入）

**不辨識、不代填、不繞過驗證碼；不替你按登入鈕。** 這是人工完成一次驗證碼後，在 Session 仍有效的前提下
自動預約的設計；不能保證登入永久有效。

| 狀態 | 意義 |
|---|---|
| `SESSION_VALID` | 偵測到有效登入，沿用，不重新登入 |
| `LOGIN_REQUIRED` | 需要登入 |
| `CAPTCHA_WAITING` | 等你在瀏覽器輸入圖片驗證碼並登入 |
| `LOGIN_VERIFYING` | 正在確認（連續兩次相同結果，再間隔複查） |
| `LOGIN_SUCCESS` | 登入已確認，才會進入預約待命 |
| `SESSION_EXPIRED` | 待命期間發現登入逾時 |
| `AUTH_FAILED` | 連續兩輪登入失敗（登入表單送出後又回來），停止，避免鎖帳號 |
| `AUTH_INTERACTION_REQUIRED` | 無法自動判斷或需要你處理（規範未同意、設備類別未確認…） |

- **判定不靠單一訊號**：必須是官方網域、沒有密碼欄位，且同時出現「登出」與（「我的紀錄」或「歡迎」）。
  探測只回傳布林值，不讀姓名、Cookie、Token 或頁面文字。
- **不盲目重登**：自動填入每次驗證最多一次；登入表單送出後又回來算一輪失敗，兩輪就停止。
- **無人回應**：等待上限預設 10 分鐘（`--login-timeout-minutes`），逾時回報 `AUTH_NO_RESPONSE`，不猜驗證碼。
- **判斷不了時**（頁面沒有預期的訊號）：進入 `AUTH_INTERACTION_REQUIRED`，GUI 才出現「已登入但偵測不到？手動確認」
  備援按鈕；只在官方網域且沒有密碼欄位時才接受。這是因為登入判定標籤尚未實機驗證（見下）。
- **待命期間的 Session 保護**（`--auth-check` 且有排程時）：
  1. 約每 60 秒一次**只讀 DOM 探測**（不發請求，不是用刷新來續命）；只有看到登入表單或被導到外站才算逾時，
     認不得的頁面不會誤判。
  2. 開始前約 5 分鐘做**一次**真實檢查（重新載入並回到日期頁）。
  3. 逾時時顯示 `SESSION_EXPIRED` 並等你重新驗證，**期限是開始前 30 秒**；來不及就放棄預約
     （`SESSION_EXPIRED_NOT_RECOVERED`），不在未知登入狀態下送出。
  4. T-10 秒預刷新與準點刷新若被導向登入頁，回報 `*_BLOCKED_SESSION_EXPIRED`，不預約。
- 電腦睡眠（`RUN_AT_MISSED`）、斷網（`REFRESH_FAILED_*`）、瀏覽器被關（`BROWSER_UNREACHABLE`）、
  Session 逾時各有獨立的結果碼與中文說明；送出後結果不明仍一律「未知，勿重送」。

### 帳密（可選）

GUI「登入與憑證」可輸入閱覽證號與密碼，存入 **macOS Keychain／Windows 憑證管理員**（`keyring`）。
不會寫入 JSON、原始碼、GitHub、日誌、環境變數或命令列；密碼欄位送出後立即清空；
沒有安全金鑰庫（或後端是明碼／空後端）時拒絕儲存。引擎只在登入頁出現時才讀取，
只填「帳號」與「密碼」兩個已驗證的欄位，**不碰驗證碼欄位、不按登入鈕**。

**登入頁欄位（已由使用者在 Mac 實機盤點，`src/ncl_openlab_site.json`）**

| 欄位 | selector | name | type |
|---|---|---|---|
| 帳號 | `input#name` | `name` | `password`（網站就是這樣設計） |
| 密碼 | `input#password` | `psword` | `password` |
| 驗證碼 | `input#insrand` | `insrand` | `text` |

三者在同一個表單，頁面路徑 `/NLT/co/login.jsp`。帳號欄位雖是 password 型別，**型別本身不構成放行理由**；
自動填入前，頁面內的檢查必須同時成立才會動作，任一不符一律不填、改由你手動登入：

1. 網域是 `spms.ncl.edu.tw`，路徑精確等於 `/NLT/co/login.jsp`（不是首頁、錯誤頁或長得像的頁面）。
2. 三個 selector 各自**剛好命中一個**元素（含隱藏的重複元素都不允許）。
3. 三個是**不同的元素**，且 id 與 name 屬性都與盤點結果一致（帳號 `name`/`name`、密碼 `password`/`psword`、
   驗證碼 `insrand`/`insrand`），型別在允許清單內（帳號 password 或 text、密碼只能 password、驗證碼只能 text）。
4. 三者屬於**同一個表單**。
5. 取得元素後再次比對其 id／name；密碼或帳號含換行等控制字元（會等同按下 Enter 而送出登入）一律拒絕。

驗證碼欄位**不會被選取、輸入或點擊**，登入鈕也不會被按；驗證碼永遠由你輸入。
本機設定檔一致性也會檢查（三個 selector 必須不同、密碼欄位只能是 password、驗證碼不可是 password）。
**僅欄位結構經實機盤點；實際填入帳密與登入結果尚未實機驗證（NOT_VERIFIED）。**
需要重新盤點時：`python src/ncl_openlab_auth.py --probe-login`（唯讀，只輸出欄位型別與名稱）。

### 使用規範（條款）

引擎只對「**你親自同意過的同一版本**」自動按「同意」：對話框文字取雜湊（只存雜湊，不存文字）。
第一次或內容更新時不會自動按，等你在瀏覽器親自閱讀並按「同意」，之後才記住該版本。
需另外勾選「允許自動按同意」。偵測不到對話框內容時一律不自動按。

### 導覽

首頁 → 使用規範對話框 → 多媒體創意實驗中心 → 設備類別（縫紉機 9 台為「創藝手作坊縫紉機」）→ 日期／設備／時段 → 最後確認。
類別與設備一律以**完全相等**的名稱比對，不模糊比對；DOM 不確定就停止。類別名未知的設備
（`entry_label: null`）由你手動開到日期頁。

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
| `--auth-check` | 以登入狀態機取代「登入後按 Enter」，並在待命期間監看 Session（GUI 一律使用） |
| `--use-saved-login` | 登入頁出現時把金鑰庫中的帳密填入（需 `--auth-check`，且登入欄位 selector 已確認） |
| `--login-timeout-minutes N` | 等你完成登入的上限（1–60，預設 10） |

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
| `test_ncl_openlab_auth` | 登入狀態機、多訊號判定、Fake Clock 的有效 Session／等待驗證碼／逾時／取消／失敗／自動填入限制、待命 Session 保護、條款版本同意 |
| `test_ncl_openlab_auth_dom` | 真實 Chromium 對假登入頁／首頁／規範對話框執行探測腳本：只回布林值、不洩漏姓名與輸入值；登入欄位檢查對正常頁、錯誤頁、欄位混淆等 20 種頁面逐一驗證 |
| `test_ncl_openlab_credentials` | 金鑰庫儲存、拒絕不安全後端、不落檔／環境變數／命令列 |
| `test_ncl_openlab_e2e_auth` | 真實引擎＋假瀏覽器（登入狀態時間軸）：沿用 Session、驗證碼等待自動確認、逾時回復或放棄、條款同意、取消 |
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
| Python 3.12 + xvfb（有 Tk，真實視窗） | **474 PASS**、0 FAIL、0 略過 |
| Python 3.13（無 Tk） | **448 PASS**、0 FAIL、**26 NOT_VERIFIED**（GUI 測試未執行） |
| macOS 實機、Windows 11 實機 | **NOT_RUN** |

沒有真實執行的測試不標 PASS：缺少 Tk／瀏覽器環境而略過者在報告中記為 `NOT_VERIFIED`。
另以故意破壞做變異驗證（提前開火、移除錯過檢查、忽略自訂時間、放寬房名比對、單一訊號判定登入、自動填入時按登入鈕、
忽略條款版本、無限等待重新登入、誤把未知頁面當逾時等），測試都能抓到。

## 仍需實機驗證的最少項目

0. **官方登入頁**：欄位結構已盤點；仍需實機確認自動填入後帳號／密碼確實落在正確欄位、登入失敗時網站的提示與行為；
   確認「登出」「我的紀錄」「歡迎」判定訊號在真站成立；實測 Session 逾時多久、逾時後網站行為；
   確認使用規範對話框的雜湊在重新載入間穩定。這些都只做過假頁面模擬。
1. **Mac 實機**：雙擊 `.command` → 視窗開啟 → Chrome 偵測 → 登入 → 待命 → 關閉視窗後 Chrome 程序與暫存目錄是否清掉（NOT_RUN）。
2. **Windows 實機**：`.cmd` 啟動、無多餘主控台視窗、高 DPI 版面（NOT_RUN）。
3. **真站不送出的演練**：用 P03（已實機驗證）選一個已開放的日期，用 `--run-at`（現在 + 1 分鐘）且**不加授權**
   （預覽模式，停在最後確認前），確認準點刷新與選取動作。
4. **設備確認頁用字**：對任一台設備實機走到最後確認頁，確認頁是否顯示設備名；之後才可考慮改為 `LIVE_VERIFIED`。
5. 睡眠／喚醒與斷網在真機的實際行為。
