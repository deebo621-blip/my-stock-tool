import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import time
import ssl

# --- 1. 基礎設定 ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

st.set_page_config(page_title="台股籌碼監控助手", layout="wide")

# --- 2. 核心功能 ---

@st.cache_data(ttl=3600)
def fetch_all_stock_ids():
    stocks = []
    try:
        urls = ['https://isin.twse.com.tw/isin/C_public.jsp?strMode=2', 
                'https://isin.twse.com.tw/isin/C_public.jsp?strMode=4']
        for url in urls:
            res = requests.get(url, verify=False)
            df = pd.read_html(res.text)[0]
            df = df[df[3] == 'ES'] 
            stocks.extend(df[0].apply(lambda x: x.split(' ')[0]).tolist())
        return [s for s in stocks if len(s) == 4]
    except:
        return ["2330", "2317", "3535", "1513"]

def get_chip_info(stock_id):
    """抓取神秘金字塔大戶籌碼"""
    url = f"https://norway.twsthr.info/StockHolders.aspx?stock={stock_id}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(res.text)[1]
        p_cols = [c for c in df.columns if '人數' in c and any(x in c for x in ['400', '600', '800', '1000'])]
        s_cols = [c for c in df.columns if '持股數' in c and any(x in c for x in ['400', '600', '800', '1000'])]
        
        latest, prev = df.iloc[0], df.iloc[1]
        diff_p = latest[p_cols].astype(float).sum() - prev[p_cols].astype(float).sum()
        diff_s = latest[s_cols].astype(float).sum() - prev[s_cols].astype(float).sum()
        
        # 只要「張數」增加就符合 (移除人數必須增加的嚴格限制)
        if diff_s > 0:
            return {
                "代碼": stock_id,
                "大戶增減張數": int(diff_s/1000),
                "大戶增減人數": int(diff_p),
                "最新大戶持股比": latest['大戶持股比率(%)']
            }
    except:
        return None
    return None

# --- 3. 網頁介面 ---

st.title("🏹 大戶吃貨追蹤器 (籌碼優先模式)")

# 讓使用者可以自己調整股價篩選門檻
momentum_filter = st.checkbox("只顯示股價強勢（接近120日高點）的股票", value=False)

if st.button("🚀 開始分析全市場 (依大戶進場量排序)"):
    all_stocks = fetch_all_stock_ids()
    st.write(f"正在檢查 {len(all_stocks)} 支股票的籌碼狀態...")
    
    results = []
    bar = st.progress(0)
    status = st.empty()
    
    # 為了避免跑太久被系統中斷，我們先跑前 300 支，或你可以調整這個範圍
    # 如果要跑全市場，請注意 time.sleep 會讓時間變長
    test_range = all_stocks # 這裡可以改成 all_stocks[:500] 先測試速度
    
    for i, s_id in enumerate(test_range):
        status.text(f"檢查中: {s_id} ({i}/{len(test_range)})")
        chip = get_chip_info(s_id)
        
        if chip:
            # 如果勾選了強勢股過濾
            if momentum_filter:
                try:
                    data = yf.download(f"{s_id}.TW", period="1y", progress=False)
                    curr = data['Close'].iloc[-1]
                    high = data['High'].iloc[-120:].max()
                    if curr < high * 0.90: # 如果低於高點 10% 就不顯示
                        continue
                    chip['目前股價'] = round(curr, 2)
                except:
                    pass
            results.append(chip)
        
        # 只有在有結果時才稍微停頓，避免被鎖 IP
        if i % 10 == 0:
            time.sleep(0.5)
        bar.progress((i+1)/len(test_range))

    if results:
        df = pd.DataFrame(results).sort_values(by="大戶增減張數", ascending=False)
        st.success(f"發現 {len(results)} 支大戶加碼股！")
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("沒搜出結果，請確認是否被網站暫時封鎖 IP。")