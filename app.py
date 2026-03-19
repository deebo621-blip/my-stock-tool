import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import time
import ssl
from datetime import datetime

# --- 1. 修正 SSL 憑證與基礎設定 ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

st.set_page_config(page_title="台股動能籌碼大數據", layout="wide")

# --- 2. 核心數據函數 ---

@st.cache_data(ttl=3600) # 每小時更新一次名單
def fetch_all_stock_ids():
    """抓取全台股上市櫃名單"""
    stocks = []
    try:
        # 上市
        res_twse = requests.get('https://isin.twse.com.tw/isin/C_public.jsp?strMode=2', verify=False)
        df_twse = pd.read_html(res_twse.text)[0]
        df_twse = df_twse[df_twse[3] == 'ES'] 
        stocks.extend(df_twse[0].apply(lambda x: x.split(' ')[0]).tolist())
        # 上櫃
        res_tpex = requests.get('https://isin.twse.com.tw/isin/C_public.jsp?strMode=4', verify=False)
        df_tpex = pd.read_html(res_tpex.text)[0]
        df_tpex = df_tpex[df_tpex[3] == 'ES']
        stocks.extend(df_tpex[0].apply(lambda x: x.split(' ')[0]).tolist())
        return [s for s in stocks if len(s) == 4]
    except Exception as e:
        st.error(f"連線證交所失敗: {e}")
        return ["2330", "2317", "3535", "1513", "2308", "2454", "3037"] # 備用清單

def check_momentum(stock_ids):
    """篩選：120日新高 + MA20 處於高位"""
    qualified = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 分批下載以提升速度
    batch_size = 40 
    for i in range(0, len(stock_ids), batch_size):
        batch = stock_ids[i:i+batch_size]
        tickers = [f"{s}.TW" for s in batch]
        status_text.text(f"📊 正在分析股價動能... ({i}/{len(stock_ids)})")
        
        try:
            # 抓取 1 年數據進行比對
            data = yf.download(tickers, period="1y", group_by='ticker', progress=False, threads=True)
            for s_id in batch:
                try:
                    s_df = data[f"{s_id}.TW"].dropna()
                    if len(s_df) < 120: continue
                    
                    # 條件：收盤價 >= 近120日最高價的 99% (容許微小誤差)
                    curr_close = s_df['Close'].iloc[-1]
                    max_120h = s_df['High'].iloc[-120:].max()
                    
                    # 條件：MA20 >= 近一年 MA20 的最高點 (這就是你要求的歷史新高邏輯簡化版)
                    ma20 = s_df['Close'].rolling(window=20).mean()
                    curr_ma20 = ma20.iloc[-1]
                    max_ma20 = ma20.max()
                    
                    if curr_close >= max_120h * 0.99 and curr_ma20 >= max_ma20 * 0.99:
                        qualified.append({'代碼': s_id, '目前股價': round(curr_close, 2)})
                except: continue
        except: continue
        progress_bar.progress(min((i + batch_size) / len(stock_ids), 1.0))
    
    status_text.empty()
    return qualified

def get_chip_info(stock_id):
    """爬取神秘金字塔：400張大戶變動"""
    url = f"https://norway.twsthr.info/StockHolders.aspx?stock={stock_id}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        df = pd.read_html(res.text)[1]
        
        # 400張以上大戶欄位定義
        p_cols = [c for c in df.columns if '人數' in c and any(x in c for x in ['400', '600', '800', '1000'])]
        s_cols = [c for c in df.columns if '持股數' in c and any(x in c for x in ['400', '600', '800', '1000'])]
        
        # 最新一週 vs 上一週
        row0, row1 = df.iloc[0], df.iloc[1]
        diff_p = row0[p_cols].astype(float).sum() - row1[p_cols].astype(float).sum()
        diff_s = row0[s_cols].astype(float).sum() - row1[s_cols].astype(float).sum()
        
        # 只要人數或張數有成長就列入，並計算成長分數
        if diff_p > 0 and diff_s > 0:
            score = (diff_p * 2) + (diff_s / 10000) # 分數演算法
            return {"400張大戶增人數": int(diff_p), "400張大戶增張數": int(diff_s/1000), "推薦分數": round(score, 2)}
    except:
        return None
    return None

# --- 3. 網頁 UI 介面 ---

st.title("🏹 強勢動能 + 大戶吃貨選股清單")
st.info("此工具會掃描全台股，找出股價在頂峰且 400 張大戶正在進場的股票。")

if st.button("🚀 開始全自動掃描 (預計需 2-3 分鐘)", type="primary"):
    all_stocks = fetch_all_stock_ids()
    
    # 第一階段：技術面過濾
    candidates = check_momentum(all_stocks)
    
    if not candidates:
        st.warning("⚠️ 目前市場上沒有股票符合「股價創 120 日新高且 MA20 創高」的嚴格條件。")
    else:
        st.write(f"🔍 第一階段：找到 {len(candidates)} 支強勢股，正在分析籌碼...")
        results = []
        chip_bar = st.progress(0)
        
        # 第二階段：籌碼面過濾
        for i, item in enumerate(candidates):
            chip = get_chip_info(item['代碼'])
            if chip:
                item.update(chip)
                results.append(item)
            time.sleep(1.1) # 關鍵：防止被神秘金字塔封鎖 IP
            chip_bar.progress((i + 1) / len(candidates))
            
        if results:
            final_df = pd.DataFrame(results).sort_values(by="推薦分數", ascending=False)
            st.success(f"🎯 掃描完成！符合所有條件的股票共 {len(results)} 支：")
            st.dataframe(final_df, use_container_width=True)
            st.balloons()
        else:
            st.warning("🕵️ 雖然有強勢股，但這些股票最新的 400 張大戶人數與張數並未同步增加。")

st.divider()
st.caption("數據來源：Yahoo Finance / 神秘金字塔。本工具僅供參考，投資請謹慎評估。")