# 保障缺口分析工具

台灣壽險業務員的保單校正＋保障缺口分析工具，輸出可展業用的 PowerPoint 分析報告。

## 技術架構

| 層   | 技術                       | Port |
|------|---------------------------|------|
| 前端 | React + Vite + Tailwind CSS | 5173 |
| 後端 | Python FastAPI              | 8000 |
| AI   | Anthropic Claude API        | —    |
| 投影片 | python-pptx + matplotlib  | —    |

## 環境設定

### 1. 建立 .env 檔

```bash
cp .env.example .env
```

填入 API Key：

```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
```

### 2. 安裝後端套件

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 安裝前端套件

```bash
cd frontend
npm install
```

## 啟動

### 後端（需先啟動）

```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload --port 8000
```

### 前端

```bash
cd frontend
npm run dev
```

開啟瀏覽器前往 **http://localhost:5173**

## 環境變數

| 變數                  | 說明                     | 必填 |
|-----------------------|--------------------------|------|
| `ANTHROPIC_API_KEY`   | Anthropic API 金鑰       | ✅   |

## 功能說明

1. **顧問設定**：首次使用時填寫業務員資料，儲存於 localStorage，PPTX 封面自動帶入
2. **客戶資料**：輸入客戶基本資料，即時計算建議壽險保額
3. **保單輸入**：新增現有保單，支援多險種、自然保費 / 平準保費
4. **AI 分析**：Claude 依標準分析缺口，生成結構化 JSON
5. **結果頁**：總覽卡片 + 趨勢圖 + 缺口紅黃綠燈 + 加保建議
6. **PPTX 下載**：6 張投影片，含封面名片、圖表、缺口說明

## PPTX 中文字體（macOS 已內建）

若在 Linux 部署，需安裝中文字體：

```bash
sudo apt-get install fonts-noto-cjk
```
