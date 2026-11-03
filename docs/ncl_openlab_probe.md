# 國圖 OPEN LAB 音樂創作室：使用時段預約輔助（唯讀）

此工具在 `feat/ncl-openlab-booking` 支線，**不接入 Tickets Hunter 主迴圈**，也不修改其他售票平台。

## 已實作

- 以台灣 UTC+8 計算預設目標日期（今天 +7 日）
- 限定國圖官方主機 `spms.ncl.edu.tw`
- 只讀取目前網頁中的目標日期、音樂創作室、三個時段的可見 DOM 候選元素
- 使用者自行登入；不紀錄密碼、Cookie、會員資料
- 不點擊、不送出、不刷新、不輪詢；沒有自動預約功能

**重要：** 截圖只證明一般預約流程；音樂創作室當時已滿，尚未驗證該空間的真實可預約 DOM、00:00 釋位秒數及網站自動化規則。偵測到文字不等於確認有空位。

## 安裝與執行（Windows PowerShell）

從儲存庫根目錄：

```powershell
pip install -r requirement.txt
python src/ncl_openlab_probe.py --date 2026-11-11 --slot 09:00-12:00
```

啟動後在新瀏覽器手動登入國圖，進入「多媒體創意實驗中心」，回終端按 Enter。程式只會輸出目標候選節點的標籤、可否點擊及可見文字摘要，**不包含預約成功的保證**。

不帶 `--date` 時，預設使用台灣當日 +7 天；不帶 `--slot` 時檢查所有標準時段。

## 離線驗證

```powershell
python -m unittest discover -s tests -p "test_ncl_openlab_probe.py"
python -m py_compile src/ncl_openlab_probe.py src/ncl_openlab_guard.py
```

## 第二刀：防誤選檢查（已加入）

- 新增 `src/ncl_openlab_guard.py`：只接受正確國圖網域、指定日期、**音樂創作室**、指定時段
- 每個目標必須唯一、文字吻合、顯示未禁用、可互動或已選取；缺少、重複、禁用皆 `BLOCKED`
- 即使三項全部吻合，只能得到 `OBSERVED_ONLY`，不能據此判定空位、點擊或送出
- 原偵測器會輸出 `dry_run_assessment`；不產生任何預約操作
- 新增十個防誤選離線案例：`python -m unittest discover -s tests -p "test_ncl_openlab_*.py"`

## 後續開發的進入條件

取得實際 DOM 偵測結果後，才能建立精準且 fail-closed 的日期/空間/時段選擇邏輯。未確認網站服務條款及 DOM 前，不做自動送出、CAPTCHA 繞過或高頻重試。

## 第三刀：改為「時段」優先，不是座位

固定空間為「音樂創作室」，只對預約 **使用時段** 排序（不涉及座位、座號或房間內位置）。

```powershell
# 第一優先晚間，其次下午；逗號後不加空白也可以
python src/ncl_openlab_probe.py --slots 17:00-20:00,13:00-16:00

# 僅查看上午時段（與原 --slot 相容）
python src/ncl_openlab_probe.py --slot 09:00-12:00
```

輸出 `time_slot_priority_plan`，包含依使用者指定優先序排列的三小時使用時段，
`first_observed` 只代表目前頁面找到的第一個候選時段，**不表示已滿/可預約狀態已獲官方確認**。
若時間文字重複、被禁用或空間不符，該時段不會成為候選。
程式仍不會點選、預約、輪詢，也不儲存登入資料。

離線測試：`python -m unittest discover -s tests -p "test_ncl_openlab_*.py"`

**尚未完成：** 需從國圖音樂創作室實際預約畫面的 DOM 確認「已滿 / 可預約」的欄位，
才能安全地轉為可執行的時段選取器。

## 第四刀：時段介面狀態證據（唯讀）

時段報告新增 `time_states`，每個時段皆附 `state`、`evidence`，而且
`availability_verified=false`、`can_book=false`。分類：

| state | 意義 |
|---|---|
| `DISABLED_UI_HINT` | 目標時段的 DOM 候選元素呈禁用訊號，**不等於正式額滿** |
| `CANDIDATE_UNVERIFIED` | 找到單一可互動候選元素，**不等於可預約** |
| `NOT_DISPLAYED` | 沒找到目標時段 |
| `AMBIGUOUS` | 同一時段有多個候選，禁止猜測 |
| `UNKNOWN` | 空間、日期、網域、控制狀態等不足以判讀 |

這些都是使用者目前開啟頁面的**視覺介面證據**，不是國圖後端的真實剩餘名額。
不可將畫面出現時間、可點擊、禁用樣式直接當作成功率或開放名額。
不會自動點選、送出、重試或搶佔時段。

此刀的離線測試：`python -m unittest discover -s tests -p "test_ncl_openlab_*.py"`；
真實可預約狀態需要從官方頁面元素進一步驗證。

## 第五刀：擷取真實時段 DOM 證據（唯讀）

執行原本的 `python src/ncl_openlab_probe.py --slots 09:00-12:00,13:00-16:00`，手動登入、進入
音樂創作室的時段畫面後按 Enter，程式會額外列出 `sanitized_time_dom_evidence`。

這份資料只包含固定時段字串、候選數、控制項標籤、禁用/選取訊號，以及白名單
狀態詞（例如「額滿」「可預約」）是否出現在同一時段附近。混入其他時段文字的容器不
使用狀態詞，以免把別的時段的狀態誤認為自己的狀態。

**隱私與安全**：不輸出網頁 HTML、任意使用者文字、帳號、密碼、Cookie、會員資料；
未通過 `validate_evidence` 會停止，不提交預約、不自動刷新、不連續輪詢。
這是「取證工具」，不宣稱已確認網站的滿位/可預約語意；仍需實機輸出與畫面對照。

離線測試：`python -m unittest discover -s tests -p "test_ncl_openlab_*.py"`；
另外執行 `python -m py_compile src/ncl_openlab_probe.py src/ncl_openlab_evidence.py`。

## 第六刀：可選擇輸出匿名診斷 JSON

要實際核對國圖音樂創作室的時段畫面，在 Windows PowerShell 於專案根目錄執行：

```powershell
python src/ncl_openlab_probe.py --save-evidence
```

程式會打開瀏覽器。請**手動登入**並進入國圖「音樂創作室」的時段選擇畫面，
回到終端按 Enter，工具才會做一次唯讀擷取。

成功輸出固定檔名 `ncl_openlab_evidence.json`（專案根目錄）：
只包含白名單的日期/空間/時段、控制項標籤、禁用訊號與固定狀態詞。
檔案已加入 `.gitignore`，不會被一般 `git add .` 收錄。
使用排他建立模式，檔案已存在時不覆蓋，避免不同日期證據混在一起。

- 原本不加 `--save-evidence` 的行為完全保留，不寫入任何檔案。
- 仍不自動選時段、不提交預約、不繞過驗證、不重試或輪詢。
- `UNVERIFIED_DOM_ONLY` 表示**只是畫面證據，並非國圖後端認證的剩餘名額**。
- 分享輸出前仍請自行核對，勿上傳含個資的完整網頁或開發者工具紀錄。

離線單元測試：
`python -m unittest discover -s tests -p "test_ncl_openlab_export.py"`。

## 第七刀：依實際國圖 HTML 變更唯讀辨識器

使用者在國圖畫面的 DevTools 確認（僅供 DOM 契約比對）：

- 空間選項：\`div.space-box1\`；已選為 \`selected\`。側邊「音樂創作室」標題不算空間選項。
- 時段選項：\`div.time-box[data-param1="HH:MM-HH:MM"]\`；\`data-param1\` 是實際時段文字。
- 觀察到已被占用的時段包含 \`class="time-box disabled reserving"\`。
- 觀察到仍可選的另一房間時段只有 \`class="time-box"\`，但這不是後端確認的空位。
- 日期、空間必須在結構化掃描中呈 \`selected\`，否則拒絕計入有效目標。
- 不使用背景色或 \`data-param3="true"\` 作為可預約判據。

\`ncl_openlab_probe.py\` 現在用結構化 DOM 選擇器找目標日期、\`space-box1\`
與精確 \`data-param1\` 時段；\`ncl_openlab_evidence.py\` 擷取固定白名單
\`class_hints\`（time-box、disabled、reserving 等），不記錄整頁文字與私人資料。
另加 \`tests/test_ncl_openlab_real_dom_contract.py\` 離線回歸案例。

**注意**：音樂創作室的三小時時段仍是唯一正式目標；「個人直播室」的一小時時段
僅作為外觀與 HTML 契約對照。禁用、可點選與預約成功是不同概念。
整個工具仍為單次唯讀檢查，不會點時段、不會送出、不會查驗證碼或輪詢。

更新本機開發分支後，用
\`.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_ncl_openlab_*.py"\`
離線複驗。需再到國圖相同選時畫面完成一次真實 DOM 驗證，才能宣稱實機通過。

## 第八刀：修正音樂創作室 time-box2 的真實 DOM

依據 **音樂創作室 2026-11-11** 的使用者提供 HTML，
三個三小時時段屬於 `div.time-box2[data-param1]`，
不同於個人直播室的一小時 `div.time-box[data-param1]`。

- 兩種時段類別均用精確 `data-param1` 查詢；正式目標仍只有音樂創作室的三小時時段。
- `disabled reserving` 是 **介面禁用訊號**；三個時段都禁用時不可推薦、不可預約。
- `data-param2="216"`、`data-param3="false"` 不用作判斷是否有名額，也不輸出到匿名證據。
- `ncl_openlab_evidence.py` 的 `class_hints` 允許 `time-box2`，同時保留既有白名單與隱私限制。
- 新增兩個回歸測試，涵蓋真實三小時 HTML 契約與全禁用 fail-closed 行為。

本刀不啟用自動點擊、登入、CAPTCHA 處理、提交或輪詢。

Windows 手動確認：在專案資料夾先 `git pull --ff-only`，再執行
` .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_ncl_openlab_*.py" -v `。
離線測試通過後，再於國圖已選日期／音樂創作室／三個時段畫面執行單次唯讀探測。

## 第九刀：日期方塊 `date-box selected` 實機契約

使用者於 2026-11-11 音樂創作室畫面的開發者工具中確認：

```html
<div class="date-box selected" id="date7">
  11/11<br><span class="weekWords">(三,Wed)</span>
</div>
```

上一版已能找到日期 1 筆、音樂創作室 1 筆與三個 `time-box2` 時段，
但曾回報 `DATE_NOT_SELECTED`。日期辨識因此改為只搜尋
`.date-box` 元素本身，以其開頭日期文字精確比對；
仍要求 **同一元素本身具有 selected**，而非誤用星期的 `span` 或其他祖先。
保留原 `DATE_NOT_SELECTED` fail-closed 防護；不會自動選日期、點時段或提交。

更新後需執行全部 `test_ncl_openlab_*.py`，再做一次國圖唯讀實機複驗，
確認禁用時段回報 `SLOT_DISABLED_OR_UNKNOWN` 而不是 `DATE_NOT_SELECTED`。

## 第十刀：保留 `book` 為唯讀 UI 提示

2026-11-11 其他空間（**個人直播室 P03**）真實可選外觀 DOM：

```html
<div class="time-box book" id="timebox0" data-param1="09:00-10:00" data-param2="1" data-param3="true">09:00-10:00</div>
```

與音樂創作室三小時時段 `time-box2 disabled reserving` 不同。
新增 `book` 至 `sanitized_time_dom_evidence.times[].nodes[].class_hints`
固定白名單（及對應驗證器），**僅供診斷**：
不代表 `availability_verified=true`，也不保證音樂創作室使用相同正向狀態。
不保存 `data-param2` 或 `data-param3`，不新增其他房間的一小時時段至目標清單。

新增回歸案例：允許 `book` 診斷 token 但仍不預約；`book` 與
`disabled reserving` 同時存在時，禁用訊號優先，始終 `BLOCKED`。
`main` 未變、無自動選取、提交、重新整理、輪詢或驗證碼操作。

更新本機後執行 `python -m unittest discover -s tests -p "test_ncl_openlab_*.py" -v`，
再到國圖音樂創作室確認三個禁用時段仍輸出 `disabled/reserving/time-box2`。
