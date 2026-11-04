# NCL OPEN LAB 多房型預約引擎

範圍：`feat/ncl-openlab-booking` 分支。不更動 `main`，不使用 GitHub Actions。
既有 P03 與音樂創作室的 CLI／GUI 行為不變（見「相容性」）。

## 一句話

房型差異全部集中在 [`src/ncl_openlab_rooms.json`](../src/ncl_openlab_rooms.json)；
引擎（`ncl_openlab_autobook.py`）只有一份程式碼，依房型設定參數化。
新增房型優先只改設定檔，測試由設定檔自動產生。

## 架構

```
ncl_openlab_rooms.json   房型與流程設定（唯一事實來源）
        |
ncl_openlab_rooms.py     載入、驗證、流程分類、支援矩陣（無瀏覽器、無副作用）
        |
ncl_openlab_autobook.py  共用引擎：ACTION_JS 依 profile 參數化；CLI
ncl_openlab_diag.py      唯讀診斷、結果碼解釋、去識別化報告、截圖
ncl_openlab_inventory.py 唯讀房型盤點與流程分類、設定草稿產生
ncl_openlab_picker*.py   GUI；房型與時段選單由設定檔產生
```

### 流程（flow）與房型（room）

- **flow**：DOM 操作模型。共用同一份引擎程式碼與同一組完整走查測試。
- **room**：房型。只有識別方式、時段清單、最後確認頁用字與實機證據。

| flow | 時段元素 | 點選前需 `book` | 選取後標記 | 目前房型 |
|---|---|---|---|---|
| `block_slot` | `.time-box2[data-param1]` | 是 | `selected` | `music` |
| `hourly_slot` | `.time-box[data-param1]` | 否 | `book` | `p03` |

`book` 在兩種流程的語意相反（P03 的 `book` 是「選取後」，曾因此誤判），
所以流程分類**不能只靠單次靜態快照**；盤點工具只給「候選」，必須實機確認。

## 支援狀態（誠實版）

| 房型 | 離線 | 實機 | 狀態 |
|---|---|---|---|
| P03 個人直播室 (`p03`) | 完整走查與負向矩陣 | 單筆實機成功（日期、房號、時段、最後確認） | **已支援（實機驗證）** |
| 音樂創作室 (`music`) | 完整走查與負向矩陣 | **NOT_VERIFIED**：無正向可預約與成交證據 | **已支援（僅離線，待實機驗證）** |
| 縫紉機01–08、刺繡機01（9 台設備，2026-11-04 實機盤點） | 與 P03 共用 `hourly_slot` 的完整走查與負向矩陣 | **NOT_VERIFIED**：只看到房型方塊與縫紉機01 的 11 個時段 | **草稿（僅離線）**：需明確確認才可送出，詳見 [NCL_SCHEDULER_CONSOLE.md](NCL_SCHEDULER_CONSOLE.md) |
| 其他房號、其他空間類別 | 無 | 未盤點 | **未支援**（見下方「新增房型」） |

待實機驗證（目前一律視為 NOT_VERIFIED，不假裝通過）：

- 音樂創作室的正向可預約 DOM、最終「預約」按鈕與成功頁。
- 同日連續兩筆預約（`--reserve-two`）：僅離線模擬。
- 午夜 T-10／T=0 刷新與 3 秒重試：離線通過，尚無自然午夜實機證據。
- `--dry-run`、`--screenshot`、`--report-dir` 在真實 zendriver 與真站上的行為：只以假瀏覽器驗證。
- `ncl_openlab_inventory.py` 在已登入的真實網站：只以合成頁面驗證。
- 網站 DOM 目前是否仍與記錄一致：fixture 是合成頁面，不能取代實機檢查。

## 新增房型（設定檔優先）

1. **盤點（唯讀，需你在自己的登入階段執行）**

   ```bash
   python src/ncl_openlab_inventory.py
   ```

   手動登入並切到各房型的選擇畫面，按 Enter 擷取。程式不點擊、不刷新、不送出。
   輸出分類結果與 `config_drafts` 草稿，寫入 `ncl_reports/`（已列入 `.gitignore`）。

2. **補齊草稿**：草稿含 `TODO`，且 `evidence.live` 是 `NOT_VERIFIED`、
   `submit_requires_ack` 是 `true`。設定載入器遇到 `TODO` 會拒絕啟用，
   必須人工填入：現況頁類別名稱 `entry_label`、最後確認頁用字 `summary_match`。
3. **併入設定檔**：貼進 `rooms` 區塊。若盤點顯示 `NEW_FLOW_UNVERIFIED`，
   代表是新流程，需另外定義 `flows` 並補一組完整走查 fixture，不能直接沿用。
4. **離線驗證**：什麼程式都不用改，既有矩陣測試會自動涵蓋新房型。

   ```bash
   python -m unittest discover -s tests -p "test_ncl_openlab_*.py"
   ```

5. **實機只讀確認**：`python src/ncl_openlab_autobook.py --date YYYY-MM-DD --room <key> --slot <時段> --dry-run`
6. **實機走完一次**後，才把 `evidence.live` 改為 `LIVE_VERIFIED`。
   在此之前，送出需要明確加上 `--ack-room-unverified`；GUI 對這類房型直接拒絕。

設定載入時會檢查（任一失敗即拒絕載入）：房間比對式不得同時命中另一房型的
樣本標籤（避免點到鄰居）、最後確認頁用字必須能比對自己的樣本、時段格式與重複、
Regex 限制（禁止巢狀量詞等）、旗標型別、`TODO` 殘留。

## CLI（既有指令不變）

新增選項：

| 選項 | 作用 |
|---|---|
| `--dry-run` | 唯讀診斷：登入後只檢查目前頁面的日期、房型、時段狀態；不可與 `--auto-submit`、`--reserve-two` 併用 |
| `--plan-only` | 只印出解析後的計畫（房型、流程、時段、預估放位時間、實機證據），不開瀏覽器 |
| `--report-dir DIR` | 寫入去識別化 JSON 診斷報告；`--dry-run` 預設 `ncl_reports` |
| `--screenshot` | 另存結束時頁面截圖；必須搭配 `--report-dir` 或 `--dry-run` |
| `--ack-room-unverified` | 對設定為 `submit_requires_ack` 的房型，明確接受未驗證風險 |

`--room` 的選項由設定檔產生，預設仍是 `music`。`--dry-run` 登入後仍會依既有邏輯
導覽大廳（只是畫面導覽，不是預約動作），之後只執行唯讀診斷。

### 報告與診斷

- `explain_outcome()` 把結果碼分成：`SUCCESS_CONFIRMED`、`RETRYABLE_BEFORE_SUBMIT`、
  `BLOCKED`、`UNKNOWN_DO_NOT_RETRY`、`WINDOW_EXHAUSTED`、`ERROR` 等，並附中文建議。
  送出後結果不明的代碼一律歸為 `UNKNOWN_DO_NOT_RETRY`。
- 報告只記錄短代碼（日期、房型、時段、旗標、各階段代碼），不記錄頁面文字、
  Cookie、帳密或表單值；追蹤欄位會過濾，不符格式者以 `REDACTED` 取代。
- **截圖可能包含姓名等個人資料**，只存本機 `ncl_reports/`，請勿提交或外傳。
- 報告寫入失敗不會改變預約結果，也不會觸發任何重試。

## 測試

```bash
python -m unittest discover -s tests -p "test_ncl_openlab_*.py"
python tests/run_ncl_offline_report.py        # 逐項 PASS／FAIL／NOT_VERIFIED 報告
```

原 162 項保留（8 項原本綁定舊原始碼字串，已改寫為檢查 profile 欄位）；
完整測試數量與排程、前端、跨平台測試見 [NCL_SCHEDULER_CONSOLE.md](NCL_SCHEDULER_CONSOLE.md)。
略過的測試在報告中記為 `NOT_VERIFIED`，不算通過。

| 測試檔 | 內容 |
|---|---|
| `test_ncl_openlab_rooms` | 設定驗證、拒絕不安全設定、流程分類、GUI 選單由設定檔產生 |
| `test_ncl_openlab_room_matrix` | **真實 Chromium** 執行引擎腳本：每個房型的完整走查（含真實滑鼠點擊）、全時段、鄰居房型不誤點、禁用／重複／缺按鈕／遮蔽／日期或時段不符／成功頁不符、單次送出守衛、大廳入口；同流程房型的差異驗證 |
| `test_ncl_openlab_legacy_parity` | 與凍結的舊版（`tests/fixtures/legacy_autobook_4d0da47.py`）逐項比對：114 組情境（2 房型 x 3 時段 x 19 種頁面變化）x 7 步驟的結果碼、23 組 CLI 參數、時段解析、入口腳本 |
| `test_ncl_openlab_diag` | 結果碼解釋、報告脫敏、診斷邏輯、`--dry-run` 不做預約動作、截圖、旗標防呆 |
| `test_ncl_openlab_inventory` | 盤點驗證與分類、設定草稿不可直接啟用、**新增房型只改設定檔即可通過整套矩陣與比對測試**（子行程驗證） |

### 相同流程如何避免逐房重測

同流程房型的引擎腳本模板逐位元組相同，payload 只允許識別欄位不同
（`room`、`mode`、`slot`、比對式、確認頁用字）；行為由完整走查與負向矩陣在
Chromium 中對每個房型自動執行。fixture 由設定檔產生，新增房型自動獲得測試。

### 測試本身的可信度

- 以故意改壞的設定做變異測試：P03 `book` 語意反轉、舊版 `SLOT_NOT_BOOK_CLASS` 缺陷、
  放寬房間比對式、放寬確認頁比對，四種全被測試抓到。
- 第一版曾有兩個測試盲點（fixture 的網站行為由設定推導造成循環論證、缺少近似房名案例），
  已修正：舊版房型的網站行為在測試中寫死為實機觀察值，並新增契約釘選測試。
- 修正過一個測試基礎設施的錯誤：Node harness 以 Buffer 分段累加字串，
  64KB 邊界會切斷中文字元，造成偶發失敗；已改為 UTF-8 串流解碼，連續 8 輪穩定。

**fixture 是依據 `docs/ncl_openlab_probe.md` 實機觀察的 DOM 合成的頁面。
它證明引擎的選取邏輯，不證明網站現況。**

## 相容性

- `action_script(phase, day, slot, mode)`、`book_one_target`、`ensure_date_grid`、
  `parse_p03_priorities`、`P03_SLOTS`、`ROOM_MODES`、`ENTRY_JS`、`ACTION_JS` 等公開名稱保留。
- `--room music|p03`、`--slot`、`--slots`、`--now`、`--auto-submit`、`--accept-terms`、
  `--reserve-two`、`--retry-*` 的語意與錯誤退出碼不變（由比對測試鎖定）。
- 結果碼、階段順序、單次送出、不重試送出、不繞驗證碼、不存帳密等安全規則不變。
- 唯一變動的既有測試：8 項直接比對舊 JS 原始碼字串（例如 `task.mode === "p03"`）。
  行為由瀏覽器比對測試取代，不是刪除。

## 邊界

不繞過 CAPTCHA、登入安全措施、預約限制或網站流量限制；不儲存帳密；
未經 `--auto-submit` 授權不送出；`--dry-run` 與 `--plan-only` 永不送出。
無法安全驗證的項目標為 NOT_VERIFIED。
