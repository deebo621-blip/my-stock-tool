import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import ssl
import time

# --- 1. 基礎設定 ---
# 你的 Token
FM_TOKEN = "EyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkYXRlIjoiMjAyNi0wMy0xOSAyMDo1NjoyMSIsInVzZXJfaWQiOiJkZWVibzYyMSIsImVtYWlsIjoiZGVlYm82MjFAZ21haWwuY29tIiwiaXAiOiIzNi4yMzMuMjIxLjEzNiJ9.WksxdgqDLf1RlFFb7jLdUyqujMsB05L54kP1NwXpWrs"

# 修正 SSL 憑證
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

st.set_page_config(page_title="台股大戶動能選股器", layout="wide")

# --- 2. 核心數據函數 (直接使用 requests 呼叫 FinMind API) ---

def get_major_chip_data(stock_id):
    """直接透過 Web API 抓取籌碼，不使用 DataLoader 以避免登入錯誤"""
    url = "https://api.finmindtrade.com/api/v4/data"
    start_date = (pd.Timestamp.now() - pd.Timedelta(days=45)).strftime('%Y-%m-%d')
    
    params = {
        "dataset": "TaiwanStockHoldingSharesPer",
        "data_id": stock_id,
        "start_date": start_date,
        "token": FM_TOKEN
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        
        if data.get("msg") != "success" or not data.get("data"):
            return None
            
        df = pd.DataFrame(data["data"])
        
        # Level 11-14 代表 400張至1000張以上
        df['Level'] = df['Level'].astype(str)
        df_major = df[df['Level'].isin(['11', '12', '13', '14'])]
        
        dates = sorted(df_major['date'].unique(), reverse=True)
        if len(dates) < 2:
            return None
        
        latest_date, prev_date = dates[0], dates[1]
        
        # 計算變動
        l_set = df_major[df_major['date'] == latest_date]
        p_set = df_major[df_major['date'] == prev_date]
        
        diff_h = l_set['holder'].sum() - p_set['holder'].sum()
        diff_s = l_set['shares'].sum() - p_set['shares'].sum()
        
        if diff_s > 0:
            return {
                "日期": latest_date,
                "大戶增減人數": int(diff_h),
                "大戶增減張數": int(diff_s / 1000),
                "分數": round((diff_s / 10000) + (diff_h * 5), 2)
            }
    except:
        return None
    return None

# --- 3. 網頁介面 ---

st.title("🏹 台股大戶動能選股器 (API 直連版)")

with st.sidebar:
    st.header("參數設定")
    stock_input = st.text_area("輸入代碼", "3535, 1513, 1609, 2330, 2317, 2454, 3231, 2382")
    run_btn = st.button("🚀 開始分析", type="primary")

if run_btn:
    stocks = [s.strip() for s in stock_input.split(',')]
    results = []
    
    prog = st.progress(0)
    for i, s_id in enumerate(stocks):
        try:
            # 120日新高檢查
            df_price = yf.download(f"{s_id}.TW", period="1y", progress=False)
            if not df_price.empty:
                curr = df_price['Close'].iloc[-1]
                high_120 = df_price['High'].iloc[-120:].max()
                
                if curr >= high_120 * 0.96:
                    chip = get_major_chip_data(s_id)
                    if chip:
                        chip['代碼'] = s_id
                        chip['價格'] = round(curr, 2)
                        results.append(chip)
        except:
            pass
        prog.progress((i + 1) / len(stocks))
    
    if results:
        st.success(f"找到 {len(results)} 支符合標的！")
        st.table(pd.DataFrame(results).sort_values(by="分數", ascending=False))
        st.balloons()
    else:
        st.warning("目前名單中無符合標的。")