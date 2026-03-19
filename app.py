import streamlit as st
import pandas as pd
import yfinance as yf
from FinMind.data import DataLoader
import time
import ssl

# --- 1. 初始化 FinMind (已帶入你的 Token) ---
FM_TOKEN = "EyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJkYXRlIjoiMjAyNi0wMy0xOSAyMDo1NjoyMSIsInVzZXJfaWQiOiJkZWVibzYyMSIsImVtYWlsIjoiZGVlYm82MjFAZ21haWwuY29tIiwiaXAiOiIzNi4yMzMuMjIxLjEzNiJ9.WksxdgqDLf1RlFFb7jLdUyqujMsB05L54kP1NwXpWrs"
api = DataLoader()
api.login_token(FM_TOKEN)

# 修正 SSL 憑證問題
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

st.set_page_config(page_title="台股大戶動能選股系統", layout="wide")

# --- 2. 核心數據處理函數 ---

def get_major_chip_data(stock_id):
    """透過 FinMind 抓取 400張以上大戶變動"""
    try:
        # 抓取最近 40 天的資料以確保包含至少兩週的週報
        df = api.taiwan_stock_holding_shares_per(
            stock_id=stock_id,
            start_date=(pd.Timestamp.now() - pd.Timedelta(days=40)).strftime('%Y-%m-%d')
        )
        
        if df.empty:
            return None
        
        # Level 11-14 代表 400張至1000張以上
        df_major = df[df['Level'].isin(['11', '12', '13', '14'])]
        
        # 取得最近兩個日期進行比對
        dates = sorted(df_major['date'].unique(), reverse=True)
        if len(dates) < 2:
            return None
        
        latest_date = dates[0]
        prev_date = dates[1]
        
        latest_set = df_major[df_major['date'] == latest_date]
        prev_set = df_major[df_major['date'] == prev_date]
        
        # 計算人數與張數
        l_holders = latest_set['holder'].sum()
        p_holders = prev_set['holder'].sum()
        l_shares = latest_set['shares'].sum()
        p_shares = prev_set['shares'].sum()
        
        diff_h = l_holders - p_holders
        diff_s = l_shares - p_shares
        
        # 條件：大戶張數增加 (人數若也增加則加分)
        if diff_s > 0:
            score = (diff_s / 10000) + (diff_h * 5)
            return {
                "日期": latest_date,
                "大戶增減人數": int(diff_h),
                "大戶增減張數": int(diff_s / 1000),
                "推薦分數": round(score, 2)
            }
    except:
        return None
    return None

# --- 3. 網頁 UI 介面 ---

st.title("🏹 台股大戶動能選股系統 (FinMind 直連版)")
st.markdown("篩選邏輯：股價接近 120 日高點 + 400張以上大戶籌碼增加")

with st.sidebar:
    st.header("參數設定")
    stock_input = st.text_area("輸入股票代碼 (逗號隔開)", "3535, 1513, 1609, 2330, 2317, 2454, 3231, 2382")
    momentum_threshold = st.slider("股價強度 (距離120日高點 %)", 80, 100, 95)
    run_btn = st.button("🚀 開始分析", type="primary")

if run_btn:
    stock_list = [s.strip() for s in stock_input.split(',')]
    results = []
    
    status = st.empty()
    bar = st.progress(0)
    
    for idx, s_id in enumerate(stock_list):
        status.text(f"正在分析 {s_id}...")
        try:
            # A. 股價動能檢查
            ticker = f"{s_id}.TW"
            df_price = yf.download(ticker, period="1y", progress=False)
            
            if not df_price.empty:
                curr_p = df_price['Close'].iloc[-1]
                high_120 = df_price['High'].iloc[-120:].max()
                
                # 符合強度門檻
                if curr_p >= high_120 * (momentum_threshold / 100):
                    # B. 籌碼檢查
                    chip = get_major_chip_data(s_id)
                    if chip:
                        chip['代碼'] = s_id
                        chip['目前股價'] = round(curr_p, 2)
                        results.append(chip)
        except Exception as e:
            continue
        
        bar.progress((idx + 1) / len(stock_list))
    
    status.empty()
    
    if results:
        final_df = pd.DataFrame(results).sort_values(by="推薦分數", ascending=False)
        st.success(f"✅ 找到 {len(results)} 支符合條件的標的！")
        
        # 顯示結果表格
        st.dataframe(
            final_df[['代碼', '目前股價', '大戶增減張數', '大戶增減人數', '日期', '推薦分數']],
            use_container_width=True
        )
        st.balloons()
    else:
        st.warning("🕵️ 掃描完畢，目前輸入的名單中沒有符合條件的股票。")

st.divider()
st.caption("數據來源：FinMind API / Yahoo Finance。大戶定義：400張以上持股者。")