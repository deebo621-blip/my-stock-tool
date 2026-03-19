import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import ssl
import urllib3

# --- 1. 基礎安全設定 ---
# 關閉 requests 的 SSL 驗證警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

st.set_page_config(page_title="台股長線突破選股器", layout="wide")

# --- 2. 獲取全市場名單與中文名稱 ---
@st.cache_data(ttl=86400)
def fetch_all_stock_info():
    """透過政府開放資料 API 抓取全市場上市櫃代碼與名稱"""
    stocks_dict = {}
    try:
        # 1. 抓取上市股票 (TWSE Open API)
        url_twse = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        res_twse = requests.get(url_twse, verify=False, timeout=15)
        data_twse = res_twse.json()
        for item in data_twse:
            code = str(item.get("Code", ""))
            name = str(item.get("Name", ""))
            if len(code) == 4 and code.isdigit():
                stocks_dict[code] = name

        # 2. 抓取上櫃股票 (TPEx Open API)
        url_tpex = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
        res_tpex = requests.get(url_tpex, verify=False, timeout=15)
        data_tpex = res_tpex.json()
        for item in data_tpex:
            code = str(item.get("SecuritiesCompanyCode", ""))
            # 上櫃的名稱欄位通常為 CompanyName
            name = str(item.get("CompanyName", item.get("SecuritiesCompanyName", "")))
            if len(code) == 4 and code.isdigit():
                stocks_dict[code] = name
                
        if not stocks_dict:
            raise ValueError("API 回傳空資料")
            
        return stocks_dict
        
    except Exception as e:
        st.error(f"連線官方 API 失敗: {e}")
        # 備用清單 (含名稱)
        return {
            "2330": "台積電", "2317": "鴻海", "2454": "聯發科", 
            "2382": "廣達", "3231": "緯創", "3535": "晶彩科", 
            "1513": "中興電", "2603": "長榮"
        }

# --- 3. 核心篩選邏輯 ---
def run_screening():
    stock_info = fetch_all_stock_info()
    all_stocks = list(stock_info.keys()) # 提取所有代碼
    
    st.info(f"📥 成功獲取 {len(all_stocks)} 支股票，正在掃描符合任一條件的標的 (預計需 2-4 分鐘)...")
    
    results = []
    bar = st.progress(0)
    status = st.empty()
    
    # 批次處理
    batch_size = 50 
    for i in range(0, len(all_stocks), batch_size):
        batch = all_stocks[i:i+batch_size]
        tickers = [f"{s}.TW" for s in batch]
        status.text(f"掃描進度: {min(i+batch_size, len(all_stocks))}/{len(all_stocks)} 支...")
        
        try:
            data = yf.download(tickers, period="max", group_by='ticker', progress=False, threads=True)
            for s_id in batch:
                try:
                    if len(batch) == 1:
                        df_s = data.dropna()
                    else:
                        df_s = data[f"{s_id}.TW"].dropna()
                        
                    if len(df_s) < 120: continue 
                    
                    curr_price = df_s['Close'].iloc[-1]
                    
                    # 條件一：120 日新高
                    high_120 = df_s['High'].iloc[-120:].max()
                    pass_cond1 = curr_price >= high_120 * 0.98
                    
                    # 條件二：月線(MA20) 歷史新高
                    ma20 = df_s['Close'].rolling(window=20).mean().dropna()
                    if len(ma20) == 0: continue
                    curr_ma20 = ma20.iloc[-1]
                    hist_max_ma20 = ma20.max()
                    pass_cond2 = curr_ma20 >= hist_max_ma20 * 0.99
                    
                    # 只要符合其中一個條件就列入
                    if pass_cond1 or pass_cond2:
                        
                        # 定義標籤與排序權重 (數字越小排越上面)
                        if pass_cond1 and pass_cond2:
                            tag = "🔥 雙重符合"
                            sort_weight = 1
                        elif pass_cond1:
                            tag = "📈 120日新高"
                            sort_weight = 2
                        else:
                            tag = "🌟 月線歷史新高"
                            sort_weight = 3
                            
                        results.append({
                            "股票代碼": s_id,
                            "股票名稱": stock_info.get(s_id, ""), # 加入中文名稱
                            "目前股價": round(curr_price, 2),
                            "符合條件": tag,
                            "排序權重": sort_weight, # 隱藏的排序基準
                            "看 K線圖": f"https://tw.stock.yahoo.com/quote/{s_id}/technical-analysis",
                            "看完整信息": f"https://tw.stock.yahoo.com/quote/{s_id}"
                        })
                        
                except: continue
        except: continue
        
        bar.progress(min((i + batch_size) / len(all_stocks), 1.0)) 
        
    status.empty()
    bar.empty()
    return results

# --- 4. 網頁介面佈局 ---
st.title("📊 台股動能與長線突破選股總表")
st.markdown("只要符合 **「股價創近120日新高」** 或 **「月線創上市以來新高」** 任一條件，即會列入下方清單。")

if st.button("🚀 開始全市場掃描", type="primary"):
    final_list = run_screening()
    
    if final_list:
        df = pd.DataFrame(final_list)
        
        # 1. 依照隱藏權重排序 (保證雙重符合在最上面)
        df = df.sort_values(by="排序權重", ascending=True)
        # 2. 排序完後，把「排序權重」這個輔助欄位刪除，不讓它顯示在畫面上
        df = df.drop(columns=["排序權重"])
        
        st.success(f"🎉 掃描完成！共發現 {len(df)} 支符合條件的股票。")
        
        # 顯示資料表與設定超連結按鈕
        st.dataframe(
            df,
            column_config={
                "看 K線圖": st.column_config.LinkColumn("📊 技術線圖", display_text="打開 K線圖 ↗"),
                "看完整信息": st.column_config.LinkColumn("📰 完整資訊", display_text="查看完整信息 ↗")
            },
            hide_index=True,
            use_container_width=True
        )
        st.balloons()
    else:
        st.warning("目前大盤環境下，沒有股票符合上述任何一個條件。")