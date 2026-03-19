import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import time
import ssl
from datetime import datetime

# --- 修正 SSL 憑證問題 (解決 Mac/Server 連線證交所失敗的問題) ---
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# --- 網頁配置 ---
st.set_page_config(page_title="台股全市場動能籌碼選股", layout="wide")
st.title("📈 台股全市場「動能+大戶」自動選股工具")
st.markdown("""
篩選邏輯：
1. **價格動能**：股價創 **120 日新高** 且 **月線 (MA20) 創歷史新高**。
2. **籌碼過濾**：檢查 **400 張以上大戶** 的人數與張數是否較上週同步成長。
3. **自動排序**：依據大戶增加幅度計算綜合分數，成長越多排越前面。
""")

# --- 核心數據抓取函數 ---

@st.cache_data(ttl=86400) # 快取名單 24 小時，避免重複抓取
def fetch_all_stock_ids():
    """從證交所抓取最新的上市櫃股票清單"""
    stocks = []
    try:
        # 上市 (TWSE)
        url_twse = 'https://isin.twse.com.tw/isin/C_public.jsp?strMode=2'
        res_twse = requests.get(url_twse, verify=False)
        df_twse = pd.read_html(res_twse.text)[0]
        df_twse = df_twse[df_twse[3] == 'ES'] 
        stocks_twse = df_twse[0].apply(lambda x: x.split(' ')[0]).tolist()
        stocks.extend(stocks_twse)

        # 上櫃 (TPEx)
        url_tpex = 'https://isin.twse.com.tw/isin/C_public.jsp?strMode=4'
        res_tpex = requests.get(url_tpex, verify=False)
        df_tpex = pd.read_html(res_tpex.text)[0]
        df_tpex = df_tpex[df_tpex[3] == 'ES']
        stocks_tpex = df_tpex[0].apply(lambda x: x.split(' ')[0]).tolist()
        stocks.extend(stocks_tpex)
        
        return [s for s in stocks if len(s) == 4] # 只取 4 碼的普通股
    except Exception as e:
        st.error(f"抓取名單失敗: {e}")
        return []

def check_price_momentum(stock_ids):
    """第一步：過濾強勢動能股"""
    qualified = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    batch_size = 50 # 分批處理避免超時
    for i in range(0, len(stock_ids), batch_size):
        batch = stock_ids[i:i+batch_size]
        tickers = [f"{s}.TW" for s in batch]
        status_text.text(f"正在分析股價動能... ({i}/{len(stock_ids)})")
        
        try:
            # 抓取 2 年數據判斷 MA20 歷史新高
            data = yf.download(tickers, period="2y", group_by='ticker', progress=False, threads=True)
            
            for s_id in batch:
                try:
                    s_data = data[f"{s_id}.TW"].dropna()
                    if len(s_data) < 120: continue

                    # 1. 120日新高
                    current_h = s_data['High'].iloc[-1]
                    max_120h = s_data['High'].iloc[-120:].max()
                    
                    # 2. MA20 創歷史新高
                    ma20 = s_data['Close'].rolling(window=20).mean()
                    curr_ma20 = ma20.iloc[-1]
                    hist_ma20_max = ma20.max()
                    
                    if current_h >= max_120h and curr_ma20 >= hist_ma20_max:
                        qualified.append({'id': s_id, 'price': s_data['Close'].iloc[-1]})
                except: continue
        except: continue
        progress_bar.progress(min((i + batch_size) / len(stock_ids), 1.0))
    
    status_text.empty()
    return qualified

def get_chip_data(stock_id):
    """第二步：抓取 400 張大戶籌碼"""
    url = f"https://norway.twsthr.info/StockHolders.aspx?stock={stock_id}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(res.text)[1]
        
        # 取得最新兩週數據
        latest = df.iloc[0]
        prev = df.iloc[1]
        
        # 定義 400 張以上欄位 (包含 400-600, 600-800, 800-1000, 1000以上)
        people_cols = [c for c in df.columns if '人數' in c and any(x in c for x in ['400', '600', '800', '1000'])]
        share_cols = [c for c in df.columns if '持股數' in c and any(x in c for x in ['400', '600', '800', '1000'])]
        
        curr_p = latest[people_cols].astype(float).sum()
        prev_p = prev[people_cols].astype(float).sum()
        curr_s = latest[share_cols].astype(float).sum()
        prev_s = prev[share_cols].astype(float).sum()
        
        # 條件：人數與張數皆增加
        if curr_p > prev_p and curr_s > prev_s:
            p_diff = curr_p - prev_p
            s_diff = (curr_s - prev_s) / 1000 # 換算成張
            # 評分：(人數增加率 * 40) + (張數增加率 * 60)
            score = ((curr_p/prev_p-1)*40) + ((curr_s/prev_s-1)*60)
            return {"增加人數": int(p_diff), "增加張數": int(s_diff), "分數": round(score, 4)}
        return None
    except:
        return None

# --- 主程式介面 ---

if st.sidebar.button("🚀 開始全市場自動選股", type="primary"):
    all_ids = fetch_all_stock_ids()
    st.info(f"已取得 {len(all_ids)} 支股票名單，開始分析動能...")
    
    # 執行第一階段篩選
    momentum_list = check_price_momentum(all_ids)
    
    if momentum_list:
        st.success(f"找到 {len(momentum_list)} 支動能強勢股，接著檢查大戶籌碼...")
        final_list = []
        chip_prog = st.progress(0)
        
        for idx, item in enumerate(momentum_list):
            res = get_chip_data(item['id'])
            if res:
                item.update(res)
                final_list.append(item)
            time.sleep(1) # 防爬蟲鎖 IP
            chip_prog.progress((idx+1)/len(momentum_list))
        
        if final_list:
            df_final = pd.DataFrame(final_list).sort_values(by="分數", ascending=False)
            st.header("🎯 最終推薦清單")
            st.dataframe(df_final, use_container_width=True)
            st.balloons()
        else:
            st.warning("符合動能但籌碼大戶未同步增加。")
    else:
        st.error("目前市場無符合動能條件之股票。")