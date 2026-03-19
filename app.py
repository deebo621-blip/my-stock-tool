import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import ssl

# --- 1. 基礎安全設定 ---
# 忽略 Mac 或伺服器連線證交所時的 SSL 憑證錯誤
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

st.set_page_config(page_title="台股長線突破選股器", layout="wide")

# --- 2. 獲取全市場名單 ---
@st.cache_data(ttl=86400) # 快取 24 小時
def fetch_all_stock_ids():
    """抓取全台股上市櫃普通股名單"""
    stocks = []
    try:
        urls = [
            'https://isin.twse.com.tw/isin/C_public.jsp?strMode=2', # 上市
            'https://isin.twse.com.tw/isin/C_public.jsp?strMode=4'  # 上櫃
        ]
        for url in urls:
            res = requests.get(url, verify=False, timeout=10)
            df = pd.read_html(res.text)[0]
            df = df[df[3] == 'ES'] # ES 代表普通股
            stocks.extend(df[0].apply(lambda x: x.split(' ')[0]).tolist())
        # 只保留 4 碼的股票代號
        return [s for s in stocks if len(s) == 4]
    except Exception as e:
        st.error("無法連線至證交所獲取名單，使用預設測試名單。")
        return ["2330", "2317", "2454", "2382", "3231", "3535", "1513"]

# --- 3. 核心篩選邏輯 ---
def run_screening():
    all_stocks = fetch_all_stock_ids()
    st.info(f"📥 已獲取全市場 {len(all_stocks)} 支股票，開始進行兩階段篩選...")
    
    # 第一階段：120 日新高篩選 (使用 1 年資料快速過濾)
    step1_pass = []
    bar = st.progress(0)
    status = st.empty()
    
    batch_size = 100
    for i in range(0, len(all_stocks), batch_size):
        batch = all_stocks[i:i+batch_size]
        tickers = [f"{s}.TW" for s in batch]
        status.text(f"第一階段 (120日新高過濾中)... 處理進度: {min(i+batch_size, len(all_stocks))}/{len(all_stocks)}")
        
        try:
            data = yf.download(tickers, period="1y", group_by='ticker', progress=False, threads=True)
            for s_id in batch:
                try:
                    df_s = data[f"{s_id}.TW"].dropna()
                    if len(df_s) < 120: continue
                    
                    curr_price = df_s['Close'].iloc[-1]
                    high_120 = df_s['High'].iloc[-120:].max()
                    
                    # 容許 2% 的拉回空間，視為創 120 日新高區間
                    if curr_price >= high_120 * 0.98:
                        step1_pass.append(s_id)
                except: continue
        except: continue
        bar.progress(min((i + batch_size) / len(all_stocks), 0.5)) # 第一階段佔進度條 50%

    if not step1_pass:
        return []

    status.text(f"✅ 第一階段通過: {len(step1_pass)} 支股票。開始第二階段 (歷史月線突破檢查)...")
    
    # 第二階段：月線 (MA20) 創上市以來歷史新高
    final_results = []
    
    # 因為名單已經大幅減少，我們可以直接下載 "max" (上市以來所有數據)
    tickers_step2 = [f"{s}.TW" for s in step1_pass]
    try:
        data_max = yf.download(tickers_step2, period="max", group_by='ticker', progress=False, threads=True)
        
        for idx, s_id in enumerate(step1_pass):
            try:
                # 處理單一股票或多股票回傳的資料結構差異
                if len(step1_pass) == 1:
                    df_max = data_max.dropna()
                else:
                    df_max = data_max[f"{s_id}.TW"].dropna()
                    
                if len(df_max) < 60: continue # 上市太短的不算歷史突破
                
                # 計算月線 (20日移動平均)
                ma20 = df_max['Close'].rolling(window=20).mean().dropna()
                curr_ma20 = ma20.iloc[-1]
                hist_max_ma20 = ma20.max()
                curr_price = df_max['Close'].iloc[-1]
                
                # 判斷：目前的 MA20 是否大於等於歷史最高 MA20 的 99% (代表剛突破或正在歷史高點)
                if curr_ma20 >= hist_max_ma20 * 0.99:
                    final_results.append({
                        "股票代碼": s_id,
                        "目前股價": round(curr_price, 2),
                        "目前月線(MA20)": round(curr_ma20, 2),
                        # 建立專屬連結
                        "看 K線圖": f"https://tw.stock.yahoo.com/quote/{s_id}/technical-analysis",
                        "看完整信息": f"https://tw.stock.yahoo.com/quote/{s_id}"
                    })
            except: continue
            
            # 更新後半段進度條
            bar.progress(0.5 + (idx + 1) / len(step1_pass) * 0.5)
            
    except Exception as e:
        st.error(f"第二階段發生錯誤: {e}")
        
    status.empty()
    bar.empty()
    return final_results

# --- 4. 網頁介面佈局 ---
st.title("📈 台股長線大波段突破選股器")
st.markdown("""
**篩選條件：**
1. 股價創近 **120 日新高**。
2. 月線 (20日均線) 創 **上市以來歷史新高**。
""")

if st.button("🚀 開始全市場掃描 (約需 1 分鐘)", type="primary"):
    results = run_screening()
    
    if results:
        df_results = pd.DataFrame(results)
        st.success(f"🎉 掃描完成！恭喜，共發現 {len(df_results)} 支剛突破歷史天際線的強勢股！")
        
        # 使用 Streamlit 的 Column Config 讓網址變成可點擊的按鈕圖示
        st.dataframe(
            df_results,
            column_config={
                "看 K線圖": st.column_config.LinkColumn(
                    "📊 技術線圖", 
                    help="點擊前往 Yahoo 股市看 K線",
                    display_text="打開 K線圖 ↗"
                ),
                "看完整信息": st.column_config.LinkColumn(
                    "📰 完整資訊", 
                    help="點擊查看財報與新聞",
                    display_text="查看完整信息 ↗"
                )
            },
            hide_index=True,
            use_container_width=True
        )
        st.balloons()
    else:
        st.warning("⚠️ 掃描完成。目前大盤環境下，沒有股票同時滿足「120日新高」與「月線歷史新高」。")