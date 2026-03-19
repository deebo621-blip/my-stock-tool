import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import time
import ssl

# 加入這兩行，強行跳過 SSL 驗證
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context
from datetime import datetime, timedelta

# --- 網頁配置 ---
st.set_page_config(page_title="台股全市場動能籌碼選股", layout="wide")
st.title("🏹 台股全市場「動能+大戶」自動選股工具")
st.markdown("""
<small>篩選邏輯：
1. **價格動能**：股價創 120 日新高 AND 月線 (MA20) 創歷史新高。
2. **籌碼過濾**：僅針對動能股，檢查神秘金字塔 400 張以上大戶的人數與張數是否較上週**同步成長**。
3. **排序**：依據籌碼成長幅度計算分數排序。
</small>
""", unsafe_allow_html=True)

# --- 核心數據抓取函數 (含快取) ---

@st.cache_data(ttl=86400) # 快取全市場名單 24 小時
def fetch_all_stock_ids():
    """從證交所抓取最新的上市櫃股票清單"""
    st.info("🔄 正在從證交所同步最新的上市櫃股票名單...")
    stocks = []
    
    try:
        # 上市 (TWSE)
        url_twse = 'https://isin.twse.com.tw/isin/C_public.jsp?strMode=2'
        res_twse = requests.get(url_twse)
        df_twse = pd.read_html(res_twse.text)[0]
        # 整理上市資料：篩選出股票，並提取代號
        df_twse = df_twse[df_twse[3] == 'ES'] # ES 代表普通股
        stocks_twse = df_twse[0].apply(lambda x: x.split(' ')[0]).tolist()
        stocks.extend(stocks_twse)

        # 上櫃 (TPEx)
        url_tpex = 'https://isin.twse.com.tw/isin/C_public.jsp?strMode=4'
        res_tpex = requests.get(url_tpex)
        df_tpex = pd.read_html(res_tpex.text)[0]
        # 整理上櫃資料
        df_tpex = df_tpex[df_tpex[3] == 'ES']
        stocks_tpex = df_tpex[0].apply(lambda x: x.split(' ')[0]).tolist()
        stocks.extend(stocks_tpex)
        
        # 移除太短的代號（通常是ETF或指數）
        stocks = [s for s in stocks if len(s) == 4]
        st.success(f"✅ 完成！共抓取到 {len(stocks)} 支上市櫃普通股代碼。")
        return stocks
    except Exception as e:
        st.error(f"❌ 抓取股票名單失敗: {e}")
        return ["2330", "2317", "3535"] # 失敗時的回退方案

def check_price_momentum(stock_ids):
    """【第一步】批量檢查股價動能 (利用 yfinance 批量下載)"""
    qualified_stocks = []
    st.info(f"⏳ 正在分析 {len(stock_ids)} 支股票的股價動能 (預計 1-3 分鐘)...")
    progress_bar = st.progress(0)
    
    # 為了穩定，分批下載 (例如每批 100 支)
    batch_size = 100
    for i in range(0, len(stock_ids), batch_size):
        batch = stock_ids[i:i+batch_size]
        tickers = [f"{s}.TW" for s in batch]
        
        # 批量下載兩年數據 (算 MA20 歷史新高通常兩年夠用，若要真歷史新高可改 period="max")
        try:
            data = yf.download(tickers, period="2y", interval="1d", group_by='ticker', progress=False, threads=True)
            
            for stock_id in batch:
                try:
                    s_data = data[f"{stock_id}.TW"]
                    # 移除 NaN 數據
                    s_data = s_data.dropna()
                    
                    if len(s_data) < 120: continue # 數據太少不分析

                    current_price = s_data['Close'].iloc[-1]
                    current_high = s_data['High'].iloc[-1]
                    
                    # 1. 120日新高 (今日高點 >= 過去120日最高點)
                    max_120h = s_data['High'].iloc[-120:].max()
                    is_120h = current_high >= max_120h
                    
                    # 2. MA20 月線創(兩年)歷史新高
                    ma20 = s_data['Close'].rolling(window=20).mean()
                    current_ma20 = ma20.iloc[-1]
                    hist_ma20_max = ma20.max()
                    is_ma20_ath = current_ma20 >= hist_ma20_max
                    
                    if is_120h and is_ma20_ath:
                        qualified_stocks.append({
                            'id': stock_id,
                            'price': current_price,
                            'ma20': current_ma20
                        })
                except: continue
        except: continue
        
        progress_bar.progress(min((i + batch_size) / len(stock_ids), 1.0))
        
    st.success(f"💥 動能篩選完成！全市場共有 {len(qualified_stocks)} 支股票股價強勢。")
    return qualified_stocks

def check_chip_growth(stock_id):
    """【第二步】抓取神秘金字塔大戶籌碼 (最容易被鎖 IP，需要極度小心)"""
    url = f"https://norway.twsthr.info/StockHolders.aspx?stock={stock_id}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://norway.twsthr.info/'
    }
    
    try:
        # 加入隨機延遲，模仿人類行為
        # time.sleep(random.uniform(1.0, 2.5)) 
        
        response = requests.get(url, headers=headers, timeout=15)
        dfs = pd.read_html(response.text)
        df = dfs[1] 
        
        if df.empty or len(df) < 2: return None
        
        # 欄位解析（注意：該網站表格結構可能變動，此處取通用索引或名稱）
        # 假設結構：人數(P)在 特定列，持股數(S)在 特定列
        # 我們需要 400-600, 600-800, 800-1000, >1000 的加總
        
        # 嘗試使用正確的欄位名稱（根據 3535 網頁結構）
        col_peo = [c for c in df.columns if '人數' in c and ('400' in c or '600' in c or '800' in c or '1000' in c)]
        col_sha = [c for c in df.columns if '持股數' in c and ('400' in c or '600' in c or '800' in c or '1000' in c)]
        
        if not col_peo or not col_sha: return None

        latest = df.iloc[0]
        prev = df.iloc[1]
        
        # 計算 >400張大戶人數與張數
        curr_p = latest[col_peo].astype(float).sum()
        prev_p = prev[col_peo].astype(float).sum()
        
        curr_s = latest[col_sha].astype(float).sum()
        prev_s = prev[col_sha].astype(float).sum()
        
        diff_p = curr_p - prev_p
        diff_s = curr_s - prev_s
        
        if diff_p > 0 and diff_s > 0:
            # 推薦分數模型：(人數成長率 * 0.4) + (張數成長率 * 0.6)
            p_pct = (diff_p / prev_p) if prev_p > 0 else 0
            s_pct = (diff_s / prev_s) if prev_s > 0 else 0
            growth_score = (p_pct * 400) + (s_pct * 600) # 放大分數方便排序
            
            return {
                "增加人數": int(diff_p),
                "增加張數": int(diff_s / 1000), # 轉為張
                "大戶持股比%": round(float(latest['大戶持股比率(%)']), 2),
                "綜合分數": round(growth_score, 2),
                "資料日期": latest['資料日期']
            }
        return None
    except Exception as e:
        # st.write(f"DEBUG: {stock_id} 籌碼抓取失敗: {e}") # 除錯用
        return None

# --- UI 介面控制邏輯 ---

with st.sidebar:
    st.header("操作面板")
    st.write("點擊按鈕開始全自動掃描 (上市櫃 ~1700+ 支)")
    st.write("**注意**：因籌碼網站有限制，動能篩選後若超過 50 支，籌碼分析可能會非常慢。")
    start_all_btn = st.button("🚀 開始全市場掃描", type="primary")
    st.divider()
    st.write(f"上次更新時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# --- 主程式執行區 ---

if start_all_btn:
    # 1. 自動抓取全市場股票名單
    all_stock_ids = fetch_all_stock_ids()
    
    # 2. 第一步：掃描股價動能
    qualified_momentum_stocks = check_price_momentum(all_stock_ids)
    
    if qualified_momentum_stocks:
        st.write("---")
        st.header(f"🕵️ 第二步：深入分析籌碼 (共 {len(qualified_momentum_stocks)} 支候選股)")
        st.info("正在連線神秘金字塔抓取 400張以上大戶數據。因必須加入延遲避免被鎖 IP，請耐心等候...")
        
        final_results = []
        chip_progress = st.progress(0)
        status_text = st.empty()
        
        # 為了安全，限制最多掃描前 80 支強勢股 (避免被鎖 IP)
        scan_limit = 80
        target_stocks = qualified_momentum_stocks[:scan_limit]
        if len(qualified_momentum_stocks) > scan_limit:
            st.warning(f"因強勢股過多，為避免被籌碼網站封鎖，目前僅分析動能最強的前 {scan_limit} 支。")

        for idx, stock_info in enumerate(target_stocks):
            s_id = stock_info['id']
            status_text.text(f"正在分析 {s_id} 的籌碼大戶 ({idx+1}/{len(target_stocks)})...")
            
            # 呼叫籌碼抓取函數
            chip_res = check_chip_growth(s_id)
            
            if chip_res:
                # 合併動能與籌碼資料
                combined_data = {
                    "股票代碼": s_id,
                    "當前股價": stock_info['price'],
                    **chip_res
                }
                final_results.append(combined_data)
            
            chip_progress.progress((idx + 1) / len(target_stocks))
            # **關鍵：** 抓取籌碼必須停頓，否則會被鎖。
            time.sleep(1.2) 
            
        # 3. 排序與顯示結果
        st.write("---")
        st.header("🎯 最終推薦選股清單 (大戶增加越多越靠前)")
        
        if final_results:
            df_final = pd.DataFrame(final_results)
            # 根據綜合分數降序排序
            df_final = df_final.sort_values(by="綜合分數", ascending=False)
            
            # 美化顯示
            st.dataframe(df_final.style.format({
                '當前股價': '{:.2f}',
                '綜合分數': '{:.2f}'
            }).background_gradient(cmap='Greens', subset=['綜合分數']), use_container_width=True)
            
            st.balloons()
        else:
            st.warning("⚠️ 雖然有強勢動能股，但目前沒有股票符合「400張大戶人數與張數同步成長」的條件。")
            
    else:
        st.error("目前全市場沒有股票符合價格動能條件（120日新高+MA20歷史新高）。")