# 國圖 OPEN LAB 音樂創作室：獨立偵測器（第一刀）

此工具在 \`feat/ncl-openlab-booking\` 支線，**不接入 Tickets Hunter 主迴圈**，也不修改其他售票平台。

## 已實作

- 以台灣 UTC+8 計算預設目標日期（今天 +7 日）
- 限定國圖官方主機 \`spms.ncl.edu.tw\`
- 只讀取目前網頁中的目標日期、音樂創作室、三個時段的可見 DOM 候選元素
- 使用者自行登入；不紀錄密碼、Cookie、會員資料
- 不點擊、不送出、不刷新、不輪詢；沒有自動預約功能

**重要：** 截圖只證明一般預約流程；音樂創作室當時已滿，尚未驗證該空間的真實可預約 DOM、00:00 釋位秒數及網站自動化規則。偵測到文字不等於確認有空位。

## 安裝與執行（Windows PowerShell）

從儲存庫根目錄：

\`\`\`powershell
pip install -r requirement.txt
python src/ncl_openlab_probe.py --date 2026-11-11 --slot 09:00-12:00
\`\`\`

啟動後在新瀏覽器手動登入國圖，進入「多媒體創意實驗中心」，回終端按 Enter。程式只會輸出目標候選節點的標籤、可否點擊及可見文字摘要，**不包含預約成功的保證**。

不帶 \`--date\` 時，預設使用台灣當日 +7 天；不帶 \`--slot\` 時檢查所有標準時段。

## 離線驗證

\`\`\`powershell
python -m unittest discover -s tests -p "test_ncl_openlab_probe.py"
python -m py_compile src/ncl_openlab_probe.py
\`\`\`

## 下一刀的進入條件

取得實際 DOM 偵測結果後，才能建立精準且 fail-closed 的日期/空間/時段選擇邏輯。未確認網站服務條款及 DOM 前，不做自動送出、CAPTCHA 繞過或高頻重試。
