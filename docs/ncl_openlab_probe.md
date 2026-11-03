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

## 第十一刀：最後「預約」頁面唯讀驗收入口

國圖流程有「選日期／空間／時段 → 下一步 → 預約」兩個不同階段。
目前**只由使用者手動前往最後頁面**，新增單次唯讀檢查，不會點擊最後的「預約」。

```powershell
.\.venv\Scripts\python.exe src\ncl_openlab_checkout_probe.py --date 2026-11-11 --slot 09:00-12:00
```

啟動後在新瀏覽器手動登入並走到最後「預約」畫面，停下，不按最終預約。
回終端按 Enter，程式只輸出 `checkout_readonly_assessment`，包含：

- 固定白名單的「下一步」「預約」「確認預約」「送出預約」「完成預約」可見數量與禁用數量
- 本頁面仍可觀察到的已選日期、房間、三小時時段是否各唯一
- `OBSERVED_ONLY` / `BLOCKED` 診斷，不包含任何預約成功的推論

**跨頁不假設上下文會保留**：如果最後頁面已移除 `date-box`、`space-box1`
或 `time-box2`，即使出現「預約」按鈕也回報 `BLOCKED`
(`FINAL_CTA_VISIBLE_CONTEXT_UNVERIFIED`)；不能從 P03 的測試推論音樂創作室成功。
輸出不讀取姓名、手機、帳號、欄位值、驗證碼、表單資料或完整網頁 HTML；
永遠 `can_click=false`、`can_submit=false`、`booking_verified=false`。

`tests/test_ncl_openlab_checkout.py` 新增 13 項獨立測試，核對網域、
日期格式、時段白名單、CTA 缺失／禁用、個人直播室參考情境、
不信任的輸入及無私密欄位外洩。

**重要**：尚未有音樂創作室正向可預約頁面的真實 DOM 證據，也未取得最後
「預約」按鈕的 outerHTML；因此這是一個可驗收的安全診斷入口，
不是已實作自動預約或送出。若網站服務條款禁止自動化，仍須遵守。

## 第十二刀：本人登入後的單次自動預約（明確選擇啟用）

新增 `src/ncl_openlab_autobook.py`，完全使用站上可見 Chrome UI，
不是呼叫未公開的後端預約 API。僅限 **音樂創作室**、指定日期及三小時
`09:00-12:00`、`13:00-16:00`、`17:00-20:00`。
使用者自行登入並進入多媒體創意實驗中心的日期畫面，之後依序自動：

1. 台北目標時間到點後**最多刷新一次**（非高頻輪詢）；
2. 找到且只點唯一、未禁用的 `.date-box` 目標日期；
3. 找到且只點唯一、未禁用的 `.space-box1` 音樂創作室；
4. 依指定時段優先順序尋找唯一 `.time-box2[data-param1]`，
   僅接受 `book` 正向 UI 標記且不含 `disabled`、`reserving`；
5. 確認所選日期、空間、時段均為 `selected`，才點一次「下一步」；
6. 最終頁需同時呈現完整日期、音樂創作室、確切時段，且有唯一
   未禁用的「預約」按鈕，才會在**明確傳入 `--auto-submit`** 時按一下；
7. 最後檢查畫面是否顯示「預約成功」及相同日期、空間、時段；
   未確認時回報 `SUBMITTED_SUCCESS_UNVERIFIED`，**絕不補點第二次**。

**使用例（以下日期只是示例，不代表必有名額）：**

```powershell
# 當日測試完整流程：不加 --auto-submit 時停在最終按鈕前
.\.venv\Scripts\python.exe src\ncl_openlab_autobook.py --date 2026-11-11 --now

# 真正單次自動預約，預設在目標使用日往前七日的台北午夜嘗試：
.\.venv\Scripts\python.exe src\ncl_openlab_autobook.py --date 2026-11-12 --slots 09:00-12:00,13:00-16:00,17:00-20:00 --auto-submit
```

以 `2026-11-12` 為例，排程時間為 **2026-11-05 00:00 台北時間**。
必須**提前 15 分鐘內**啟動且保持程式與 Chrome 開啟，登入後進到日期畫面按 Enter。
因網站只官方公布「使用前七日開放」，**確切午夜秒數尚非官方驗證規則**；
腳本採先前使用者觀察的 00:00 作預設，若官網調整應停止而非高速嘗試。

想立刻嘗試（非開放當下）可加 `--now --auto-submit`，但這將**真的提交**
任何符合防護條件的時段。沒有 `--auto-submit` 不按最後預約。

**邊界**：不得使用別人的借閱證；不得超出官方每人每週／每日限制；
沒有 CAPTCHA 解題或繞過驗證、沒有高速輪詢或重試提交、
沒有多帳號操作、沒有儲存帳密、姓名、電子郵件或證號。
如果最後頁面的房名、日期、時段不一致，停止。
目前只有個人直播室的可選 DOM 作為正向類別參考，
音樂創作室正向可用的 `time-box2.book` 與最終按鈕尚**未實機通過**，
因此不保證搶位成功。網站若禁止自動化，應停用此模式。

新增 `tests/test_ncl_openlab_autobook.py` 17 個離線安全測試，
執行全部 `test_ncl_openlab_*.py` 進行驗收。

## 第十三刀：P03 個人直播室「真實送出」測試模式

此模式與原「音樂創作室」共用 **單次** 實機預約引擎，
但使用互不混用的目標清單及 DOM 選擇器：

- `--room music`（預設）只找「音樂創作室」、三小時 `time-box2`。
- `--room p03` 只找 **個人直播室 P03**（以 `space-box1` 起始完整 P03 房號辨識）
  與指定的一小時 `.time-box[data-param1]`。
- P03 **必須**指定單一 `--slot`，不能選別間直播室、不能使用三小時時段。
- 唯有 `book` 正向 UI 訊號且沒有 `disabled/reserving` 才會嘗試。
  這不代表官方確認名額，真正以預約結果頁驗證。
- 程式須看到目標日期與 P03 已選、目標時段已選，才按「下一步」；
  最終頁須同時包含 **完整日期、P03、個人直播室、時段** 才能按一次「預約」。
  頁面使用直排中文字時，僅將空白正規化來比對，不讀取／儲存表單個資。
- `--auto-submit` 明確授權**真的送出一次**。送出後**不重送**；
  保持瀏覽器開啟供確認，手動按 Enter 才結束。

**範例（如已使用過該時段或無實際需求，勿重複預約）：**

```powershell
# 11/11 P03 下午 13:00–14:00，立刻嘗試真正送出一次
.\.venv\Scripts\python.exe src\ncl_openlab_autobook.py --room p03 --date 2026-11-11 --slot 13:00-14:00 --now --auto-submit
```

開啟瀏覽器後手動登入、進入多媒體創意實驗中心日期畫面，按 Enter
即可開始流程，無需人工點選 P03 或「預約」。如日期未開放、被禁用、
房號不符、時段未開放、最終頁資訊不符則自動停止。
**尚未實機驗證 P03 這條真實自動送出路徑。**
此模式不繞過驗證碼、不儲存個資、不高速刷站。

截至 2026-11-04 官方規定：7 日內其他同一空間最多 4 個時段、
每天最多 2 個時段、同一時段僅供預約一個空間或設備；
執行前請自行確認未超過限制：
https://www.ncl.edu.tw/regulations/0Q090387295603483412

P03 新增 `tests/test_ncl_openlab_p03_autobook.py` 回歸測試，
整批執行 `python -m unittest discover -s tests -p "test_ncl_openlab_*.py" -q`。

## 第十四刀：P03 時段選取狀態實機修正

2026-11-04 本機 P03 13:00–14:00 實測：
`date: CLICKED`、`room: CLICKED`、`slot 13:00-14:00: SLOT_NOT_BOOK_CLASS`。
截圖當時該時段仍為棕色未選取，程式未按「下一步」、未送出預約。

根因：先前將 P03 的 `book` 類別當作**選取前條件**；
但已觀察到的 `div.time-box.book` 是在使用者**選取該時段之後**的 HTML。
修正如下：

- P03 僅限唯一 `.time-box[data-param1]`，且不含 `disabled`、
  `is-disabled`、`reserving`、`unavailable` 或 HTML 禁用狀態時，
  允許從未選取棕色 `.time-box` 點選。
- P03 `.time-box.book` 視為**已選時段**，並要求此狀態存在，才可按「下一步」。
- 音樂創作室 `.time-box2` 的原有防護及 `book` 要求維持不變。
- 仍以 P03、日期、時段三項比對最後確認頁，僅在 `--auto-submit`
  明確啟用時按一次最終「預約」，絕不重試送出。

新增 3 項回歸測試。此修正**尚未完成新的 P03 實機預約驗證**。

## 第十五刀：修正 P03 最後「預 約」按鈕

2026-11-04 P03 13:00–14:00 的實機截圖證明，程式已成功自動按「下一步」，
最後頁清楚顯示目標日期、P03、正確時段，以及圓形「預 約」按鈕，
但當次**尚未確認最終按鈕點擊及預約成功**。

修正最後 CTA 文字比對：只對固定白名單「下一步／預約」
移除標籤內的空白，令 `預約`、`預 約` 都視為同一**完整文字**；
不接受含有其他字符的文字或模糊子字串。獨立選擇最內層
匹配的 DOM 元素，優先使用相應可見的互動祖先，仍要求唯一、
未禁用的 CTA，且先通過日期、P03、時段的完整核對。
最終按鈕仍僅在 `--auto-submit` 明確同意時點一次；提交後不重試。

新增兩項回歸測試：含空白按鈕的正規化、一次提交守衛。
下一次實機測試仍應檢查終端 `submit:` 的確切診斷碼；
若結果為 `SUMMARY_MISMATCH`，不可推定是按鈕問題。

## 第十六刀：午夜入口、精確 `#gobook` 與兩時段序列預約

使用者提供國圖真實 DOM：

```html
<div class="art-image multimedia hover"></div>
<button id="agree-btn" class="button agree">同意 Agree</button>
<button class="submit-circle-button" data-en="Reserve" data-zh="預 約"
  id="gobook" data-param2="2026-11-11" data-param5="13:00-14:00">預 約</button>
```

不使用、也不儲存 `#gobook` 其他動態 `data-param*` 值。

**入口**：登入後若仍在首頁，會僅一次導向 `.art-image.multimedia`。
如需按「同意 Agree」，使用者可在午夜前親自閱讀並點擊；
只有明確傳入 `--accept-terms` 才允許程式自動點擊
`#agree-btn.button.agree`。無法唯一辨識、條款文字變更或日期格未出現即停止。
準點到達目標日之前 7 日台北 00:00，最多只刷新一次；刷新後也檢查入口。

**最後預約**：只辨識唯一可見 `button#gobook.submit-circle-button`，
同時要求完整日期／空間／時段畫面摘要與 `data-param2` 日期、
`data-param5` 時段精確吻合，且點擊位置沒有遮蔽物。
透過瀏覽器 `tab.mouse_click(x,y)` 發出一次滑鼠事件，
避免僅做 JS `HTMLElement.click()` 就誤以為成功。
按過後不重試；僅真實「預約成功」且日期、空間、時段都一致才判 PASS。
`CLICKED_ONCE` 不是成功；未確認時必須查官方「我的紀錄」。

**同日兩段**，只支援音樂創作室兩個不同三小時時段，
使用單一瀏覽器登入，依使用者給定順序**最多兩筆**：
第一筆完整確認成功後才重入首頁準備第二筆；
若任一筆失敗或結果不確定，立即停止，不會重送／高速輪詢。

```powershell
# 例如：2026-11-12 下午優先、晚間第二。這是實際送出指令。
.\.venv\Scripts\python.exe src\ncl_openlab_autobook.py --room music --date 2026-11-12 --slots 13:00-16:00,17:00-20:00 --reserve-two --auto-submit --accept-terms
```

開始前需親自登入網站、了解同意條款、在日期格頁按 Enter。
不加 `--now` 時只可於預定午夜前 15 分鐘內執行並待命。
以台北時區 `YYYY-MM-DD 00:00:00` 為假定放位時刻；
這是使用者確認的操作需求，官網並未明示可保證精確到秒。

**每日最多兩個時段含既有預約**。例如同日已經訂過個人直播室一段，
剩餘當天名額可能只剩一段，不應再下雙時段指令。
音樂創作室還需符合官方最低使用人數規則。
禁止重覆嘗試、跳過頁面條款、驗證碼或反機器人機制；
遵守官方預約規則及可能的網站自動化限制。

這部分新增多項離線回歸測試，但**尚無音樂創作室正向實機成交證據**，
也未證明能在午夜成功預約兩筆。請先跑完單元測試，
再驗證 P03 的單次實機最終滑鼠送出確實成功，
才能開啟兩段正式預約。

## 第十七刀：修正多媒體空間現況頁到 7 日日期格的入口

2026-11-04 實機觀察：
- 先前程式在 `DATE_GRID_NOT_READY_ENTRY_NOT_FOUND_OR_AMBIGUOUS` 停止，
  當時網址為 `/NLT/co/multimedia.jsp`，無 `.date-box`、
  `.art-image.multimedia`、`#agree-btn`，不是日期頁。
- 在空間現況頁，使用者提供 `div.lab-item#media_seat_8` 內含
  `div.lab-name[data-zh="個人直播室"]`，手動點擊後跳到
  `/NLT/co/media_discussion.jsp`，此頁有 **7 個** `.date-box`。

修正 `ENTRY_JS`：只在官方主機的 `/NLT/co/multimedia.jsp`
尋找**唯一、可見、未禁用**的
`.lab-item .lab-name[data-zh]`。P03 模式只接受
`個人直播室`，音樂創作室模式只接受 `音樂創作室`，
點擊其最近的 `.lab-item` 一次後，等待真正日期格出現。
不採用網頁中動態或跨日的 session ID，進入日期格後仍需精確選
P03（而非其他直播室）或音樂創作室、日期、時段才能進下一步。
錯誤或不唯一就停止，不猜測也不跨空間點擊。

入口增加 4 項回歸測試；截至此 commit 尚未實機複驗。

## 第十八刀：P03 最終按鈕改用 Zendriver Element.click

2026-11-04 P03 真實送出測試：`date`、`room`、`slot`、
`next` 全部 `CLICKED`，`submit: CLICKED_ONCE`，但使用者
在官方「我的紀錄」確認**沒有新增預約**，最後畫面仍停在「預 約」。
因此必須把前次的 `CLICKED_ONCE` 視為「鼠標事件已發送」，
不代表後端受理。

查看 Zendriver Python API：`Tab.mouse_click` 只送出
`mousePressed/mouseReleased`，`Element.click` 則以
`Runtime.callFunctionOn(..., user_gesture=True)` 執行元素點擊。
本刀**改成單一** `tab.select("button#gobook.submit-circle-button")`
後 `element.click()`，不用原本座標 `tab.mouse_click`。
提交前仍須通過完整日期、房間、時段、按鈕 `data-param2/data-param5`
和畫面可見／未遮蔽檢查；一旦準備提交就絕不補點第二次，
若瀏覽器逾時或結果不明必須手動查「我的紀錄」。

顯示 `submit method: ZENDRIVER_ELEMENT_CLICK` 以區分舊版實機紀錄。
僅在實機成功畫面或官方「我的紀錄」有新紀錄時才算預約成功。

## 第十九刀：原生鍵盤啟動 + 唯讀 click/AJAX 診斷

2026-11-04 使用者手動按 `#gobook` 後，Network 確認
`step2_media.jsp` 回應 HTTP 200，並開啟 `success_media.jsp`，
官方「我的紀錄」確實出現 P03 預約。**只有手動預約獲證實。**

相對地，前版的 `ZENDRIVER_ELEMENT_CLICK` 雖印出
`CLICKED_ONCE`，仍停在預約確認頁，使用者確認沒有預約紀錄。
後續以 Element.click 送出成功是**未驗證的說法**，不能當成通過。

Zendriver Python 官方文件指出 `Element.click()` 執行 JS
`el.click()`；`Element.send_keys(SpecialKeys.SPACE)` 則在目標
聚焦後由 CDP 發送原生鍵盤 keydown/keyup。此版以**唯一一次 Space
原生鍵啟動**代替 JS 點擊和座標點擊，不做後備第二次提交。

送出前的 JS 只核對日期、房名、時段、按鈕、畫面狀態。
另在按鈕加入被動 `click` 觀察器，及 jQuery `ajaxSend`
觀察器，終端只回傳 `click/trusted/ajax` 三個布林指標：
不讀取 Email、個資、POST body，也不攔截或重送請求。
實際成功依舊要用國圖成功頁及「我的紀錄」驗證。
目前本修正**尚未經實機驗收**；目前若已有同時段預約，禁止重測送出。

## 第二十一刀：午夜預刷新 + 限時搶位 LOOP + 時段優先序

2026-11-04 P03 實機畫面顯示 `OK 預約成功`，
日期 2026-11-11、時段 13:00–14:00；此為一次真實預約的使用者截圖。
正式午夜搶位與多時段的實際成功則**尚未驗證**。

### 午夜排程（台北時間，使用日往前 7 天）

- 23:59:50：若提前登入並已停在日期頁，僅預刷新一次。
- 00:00:00：必須再正式刷新一次；不因預刷新而提前選未開放日期。
- 如目標日期尚未出現／標為禁用，或所有指定時段都沒有可選的
  正向介面訊號：預設每 **3 秒**再次刷新，最多 **90 秒**。
  不會每秒或無限刷新。可調 `--retry-interval 3..30`、
  `--retry-window 0..180`。若國圖不允許自動重刷，請勿啟用。
- 午夜判定來自本機系統時間（`Asia/Taipei`），而非國圖伺服器同步時鐘；
  實際刷新受網路與瀏覽器載入時間影響，**不能保證毫秒級準點**。
- 重新檢查僅限「尚未看見可預約的日期或時段」。
  一旦已選到時段並開始確認／送出，只允許**一次最終預約**，
  成功、失敗或未知都停止 LOOP，不會為了補位而重複提交。
- 第一筆未確認成功，雙時段模式不進入第二筆。仍須遵守每天最多
  兩個時段（含已有預約）、房間最低使用人數及網站規範。

### 時段選擇

用 `--slots` 按優先順序指定，**沒有 `--reserve-two` 只預約第一個可選時段一次**：

```powershell
# 音樂創作室：下午優先，下午不可預約才嘗試上午、晚上（僅預約一段）
.\.venv\Scripts\python.exe src\ncl_openlab_autobook.py --room music --date 2026-11-12 --slots 13:00-16:00,09:00-12:00,17:00-20:00 --auto-submit

# 音樂創作室：真的需要兩段，依序預約兩個時段
.\.venv\Scripts\python.exe src\ncl_openlab_autobook.py --room music --date 2026-11-12 --slots 13:00-16:00,17:00-20:00 --reserve-two --auto-submit

# 個人直播室 P03：13 點優先，14 點備選，只送出一筆
.\.venv\Scripts\python.exe src\ncl_openlab_autobook.py --room p03 --date 2026-11-12 --slots 13:00-14:00,14:00-15:00 --auto-submit
```

`--now` 仍只會立即測試一次，**不進行午夜等待或重試**；
不可誤把午夜重試流程的測試輸出當成真實預約成功。
預約前必須本人登入、閱讀並同意條款，完成後按 PowerShell Enter 開始待命。

## 第二十二刀｜Windows 月曆與時段複選器

在專案根目錄雙擊 `launch_ncl_picker.cmd`（或在 PowerShell 執行
`.\.venv\Scripts\python.exe src\ncl_openlab_picker.py`，視所在工作目錄調整）。
不需額外 pip 安裝 GUI 套件：使用 Python 內建 `tkinter`。

- 月曆顯示本地台北日期，按上／下個月切換，可點日期；預設為下次午夜
  可能放位的日期（台北今日 +8 天），並在畫面顯示預定放位日
  `預約日 -7 天 00:00`，**不是宣稱網站一定會準點放位**。
- 可切換 `音樂創作室`（09–12、13–16、17–20）或 `P03 個人直播室`
  （09–20，每小時一段）。這些是現有預約頁面觀察的時段清單，
  不是當天的即時可預約性；最終仍由官方介面判斷。
- 點選時段可**複選最多兩個**。選取順序就是送出順序；
  選一個只預約一筆，選兩個則自動加 `--reserve-two`，在**同一
  登入環境中依序做兩次完整預約**。第一筆沒有官方成功確認就停止，
  不會進第二筆、不會重送第一筆。
- 另有「立即執行」測試切換（關閉午夜等待）、是否同意條款及
  **明確允許真正送出預約**勾選框。沒有授權就不能啟動。
- 午夜模式必須在放位前 15 分鐘內啟動；啟動後瀏覽器供使用者
  手動登入與確認條款，PowerShell 終端按 Enter 後待命。
  預定 23:59:50 預刷新；00:00 正式刷新，未開放時每 3 秒
  重試、最多 90 秒。沒有連續無界重刷。
- 點「確認設定並開啟預約瀏覽器」後，先以完整日期、房間及時段清單
  再確認一次；若允許，使用 `python.exe` 開啟獨立 Windows 主控台，
  保留必要的手動登入互動。UI 本身不儲存帳密或存取個人預約資料。

**注意**：日期／時段選擇器本身尚未經 Windows 視覺實機驗收，
但它所呼叫的 P03 單筆自動預約在 2026-11-04 有使用者
提供的真實 `OK 預約成功` 畫面；雙時段先由離線測試保護。
