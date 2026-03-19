import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import time
import ssl

# --- 1. 基礎設定與 SSL 修正 ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

st.set_page_config(page_title="台股大戶動能選股器", layout="wide")

# --- 2. 核心功能 ---

@st.cache_data(ttl=3600)
def fetch_all_stock_ids():
    """抓取全市場名單"""
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
        return ["2330", "2317", "3535", "1513", "1504", "2308", "2454"]

def check_momentum(stock_ids):
    """第一階段：股價強勢度過濾"""
    qualified = []
    bar = st.progress(0)
    status = st.empty()
    
    batch_size = 50
    for i in range(0, len(stock_ids), batch_size):
        batch = stock_ids[i:i+batch_size]
        tickers = [f"{s}.TW" for s in batch]
        status.text(f"🔍 掃描股價動能中... ({i}/{len(stock_ids)})")
        
        try:
            # 抓取 1 年數據
            data = yf.download(tickers, period="1y", group_by='ticker', progress=False, threads=True)
            for s_id in batch:
                try:
                    s_df = data[f"{s_id}.TW"].dropna()
                    if len(s_df) < 60: continue
                    
                    curr_price = s_df['Close'].iloc[-1]
                    high_120d = s_df['High'].iloc[-120:].max()
                    ma20 = s_df['Close'].rolling(window=20).mean()
                    
                    # 條件：股價距離 120日高點 5% 以內 (相對強勢)
                    if curr_price >= high_120d * 0.95:
                        qualified.append({'代碼': s_id, '目前股價': round(curr_price, 2)})
                except: continue
        except: continue
        bar.progress(min((i + batch_size) / len(stock_ids), 1.0))
    status.empty()
    return qualified

def get_chip_info(stock_id):
    """第二階段：神秘金字塔大戶籌碼"""
    url = f"https://norway.twsthr.info/StockHolders.aspx?stock={stock_id}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(res.text)[1]
        
        # 400張以上大戶相關欄位
        p_cols = [c for c in df.columns if '人數' in c and any(x in c for x in ['400', '600', '800', '1000'])]
        s_cols = [c for c in df.columns if '持股數' in c and any(x in c for x in ['400', '600', '800', '1000'])]
        
        latest, prev = df.iloc[0], df.iloc[1]
        diff_p = latest[p_cols].astype(float).sum() - prev[p_cols].astype(float).sum()
        diff_s = latest[s_cols].astype(float).sum() - prev[s_cols].astype(float).sum()
        
        # 條件：大戶張數必須增加 (這是核心)
        if diff_s > 0:
            # 分數：張數增加權重 80%，人數增加權重 20%
            score = (diff_s / 1000 * 0.8) + (diff_p * 0.2)
            return {
                "大戶增減張數": int(diff_s/1000),
                "大戶增減人數": int(diff_p),
                "推薦分數": round(score, 2),
                "查看詳情": f"https://norway.twsthr.info/StockHolders.aspx?stock={stock_id}"
            }
    except:
        return None
    return None

# --- 3. 網頁介面 ---

st.title("🏹 台股強勢動能 + 大戶吃貨篩選器")

tab1, tab2 = st.tabs(["全市場掃描", "單一股票檢查"])

with tab1:
    if st.button("🚀 開始全自動掃描", type="primary"):
        all_stocks = fetch_all_stock_ids()
        st.write(f"已獲取 {len(all_stocks)} 支股票，正在篩選動能標的...")
        
        candidates = check_momentum(all_stocks)
        
        if candidates:
            st.write(f"找到 {len(candidates)} 支強勢股，正在分析大戶籌碼...")
            results = []
            chip_bar = st.progress(0)
            for i, item in enumerate(candidates):
                chip = get_chip_info(item['代碼'])
                if chip:
                    item.update(chip)
                    results.append(item)
                time.sleep(1.1) # 避免被鎖 IP
                chip_bar.progress((i+1)/len(candidates))
            
            if results:
                df = pd.DataFrame(results).sort_values(by="推薦分數", ascending=False)
                st.dataframe(df, use_container_width=True)
                st.balloons()
            else:
                st.warning("目前強勢股中，沒有大戶正在加碼的標的。")
        else:
            st.error("目前市場上沒有符合動能條件的股票。")

with tab2:
    test_id = st.text_input("輸入股票代碼測試 (例如: 3535)", "3535")
    if st.button("檢查籌碼"):
        chip_test = get_chip_info(test_id)
        if chip_test:
            st.success(f"股票 {test_id} 符合大戶增加條件！")
            st.write(chip_test)
        else:
            st.error(f"股票 {test_id} 大戶張數未增加。")