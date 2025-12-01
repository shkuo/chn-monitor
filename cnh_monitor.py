import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import time
from datetime import datetime
import json
import random

# --- 設定頁面 ---
st.set_page_config(
    page_title="CNH 爆貶戰情監控室",
    page_icon="🇨🇳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 數據抓取模組 ---

@st.cache_data(ttl=60)  # 設定緩存 60 秒，避免頻繁請求被封鎖
def get_yahoo_data():
    """從 Yahoo Finance 獲取基礎匯率與金價"""
    tickers = ["CNY=X", "CNH=X", "HKD=X", "GC=F"]
    try:
        data = yf.download(tickers, period="1d", interval="1m", progress=False)
        # 取得最新一筆數據 (iloc[-1])
        # 注意: yfinance 返回格式如果是 MultiIndex，需要特別處理
        
        result = {}
        # 處理 yfinance 可能返回的格式差異
        try:
            df = data['Close']
            result['cny'] = df['CNY=X'].iloc[-1]
            result['cnh'] = df['CNH=X'].iloc[-1]
            result['hkd'] = df['HKD=X'].iloc[-1]
            result['gold_intl'] = df['GC=F'].iloc[-1]
        except:
             # Fallback 處理單一 ticker 或不同結構
             for t in tickers:
                 result[t] = data['Close'][t].iloc[-1]
                 
        return result
    except Exception as e:
        st.error(f"Yahoo Finance 數據獲取失敗: {e}")
        return None

def get_shanghai_gold():
    """
    爬取新浪財經 API 獲取上海黃金交易所 Au99.99 現貨價格
    URL: http://hq.sinajs.cn/list=gds_Au99_99
    """
    url = "http://hq.sinajs.cn/list=gds_Au99_99"
    headers = {"Referer": "https://finance.sina.com.cn/"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            # 格式: var hq_str_gds_Au99_99="380.00,380.00,381.50,..."
            text = response.text
            data_str = text.split('"')[1]
            data_parts = data_str.split(',')
            current_price = float(data_parts[0])  # 最新價
            # 如果收盤導致最新價為 0，取昨收 (index 7) 或其他非零值
            if current_price == 0:
                 current_price = float(data_parts[7])
            return current_price
    except Exception as e:
        # st.warning(f"上海金價爬取失敗: {e}") # Debug 用
        pass
    return None

def get_binance_usdt_cny():
    """
    嘗試從幣安 P2P API 獲取 USDT/CNY 買單價格
    注意：此接口極易變動或需要特定 Headers，若失敗則返回 None
    """
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    payload = {
        "page": 1, "rows": 5,
        "payTypes": [], "asset": "USDT", "tradeType": "BUY",
        "fiat": "CNY", "publisherType": None
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            # 取第一筆廣告的價格 (通常是最優價)
            if data['data']:
                price = float(data['data'][0]['adv']['price'])
                return price
    except Exception as e:
        # st.warning(f"USDT 爬取失敗 (可能被擋): {e}")
        pass
    return None

def get_cnh_hibor():
    """
    嘗試從東方財富網 API 獲取香港人民幣隔夜拆息 (HIBOR O/N)
    代碼: 00000001 (HKCNH HIBOR ON) -> 需要確認東方財富具體代碼
    這裡使用備用邏輯：模擬或抓取匯率網
    為求穩定，這裡演示爬取 'Sina Finance' 全球市場數據或直接給予模擬值(若爬取失敗)
    """
    # 東方財富 API (香港銀行同業拆息 - 人民幣)
    # 實際爬蟲極不穩定，為保證演示效果，若抓不到我們使用一個基於市場的估算值或顯示 N/A
    
    # 嘗試: http://push2.eastmoney.com/api/qt/stock/get?secid=100.HKCNH0N ...
    # 這裡為避免程式碼過於複雜且易失效，我們先嘗試返回 N/A，使用者需手動查
    # 但為了 Demo，我們寫一個模擬的 "正常範圍隨機波動" 若爬取失敗
    
    return None # 暫時返回 None，在 UI 層處理

# --- 核心邏輯 ---

def calculate_metrics(yahoo_data, sh_gold, usdt_cny):
    if not yahoo_data:
        return None

    cny = yahoo_data['cny']
    cnh = yahoo_data['cnh']
    hkd = yahoo_data['hkd']
    gold_intl_usd = yahoo_data['gold_intl']

    # 1. 價差 (Spread in pips)
    spread = (cnh - cny) * 10000

    # 2. 黃金溢價 (Shanghai Premium)
    # 國際金價 (USD/oz) -> 人民幣/克
    # 1 oz = 31.1035 g
    gold_intl_cny_g = (gold_intl_usd / 31.1035) * cny
    
    gold_premium = 0
    if sh_gold:
        gold_premium = (sh_gold / cny * 31.1035) - gold_intl_usd # 用每盎司美元價差顯示
        # 或者顯示每克人民幣價差: gold_premium_cny = sh_gold - gold_intl_cny_g

    # 3. USDT 溢價
    usdt_premium_pct = 0
    if usdt_cny:
        # 官方匯率通常參考 CNY=X 或 CNH=X，這裡用 CNH 作為基準比較
        usdt_premium_pct = ((usdt_cny - cnh) / cnh) * 100

    return {
        "cny": cny,
        "cnh": cnh,
        "hkd": hkd,
        "spread": spread,
        "gold_intl_usd": gold_intl_usd,
        "sh_gold": sh_gold,
        "gold_premium": gold_premium,
        "usdt_cny": usdt_cny,
        "usdt_premium": usdt_premium_pct,
        "timestamp": datetime.now()
    }

def get_status_color(level):
    if level == "critical": return "🔴"
    if level == "warning": return "🟡"
    return "🟢"

def analyze_risk(metrics, hibor_val):
    risk_report = {"level": "normal", "msg": "目前指標平穩，維持觀望。", "color": "green"}
    
    if not metrics:
        return risk_report

    # 邏輯判斷
    is_spread_high = metrics['spread'] > 500
    is_spread_critical = metrics['spread'] > 1000
    is_cnh_breakout = metrics['cnh'] > 7.35
    is_capital_flight = metrics['gold_premium'] > 30 or metrics['usdt_premium'] > 2.0
    is_hibor_squeeze = hibor_val is not None and hibor_val > 10

    if is_hibor_squeeze:
        risk_report = {
            "level": "critical", 
            "msg": "⚠️ 緊急撤退 (Emergency Exit)：偵測到流動性夾殺 (HIBOR 飆高)，央行暴力干預中。停止做空，保留現金。",
            "color": "purple"
        }
    elif is_cnh_breakout and is_spread_critical:
        risk_report = {
            "level": "critical", 
            "msg": "🔥 全力行動 (Full Action)：匯率突破 7.35 且價差失控 (>1000點)。趨勢確立，分批轉移資產。",
            "color": "red"
        }
    elif is_spread_high or is_capital_flight:
        risk_report = {
            "level": "warning", 
            "msg": "🛡️ 高度警戒 (High Alert)：偵測到聰明錢外逃或做空壓力增加。密切監控 7.35 關卡。",
            "color": "orange"
        }

    return risk_report

# --- UI 渲染 ---

def main():
    # Header
    st.title("🇨🇳 CNH 爆貶戰情監控室 (Python Live Ver.)")
    st.markdown("數據來源：Yahoo Finance (API), 新浪財經 (爬蟲), Binance P2P (爬蟲)")
    
    if st.button('🔄 立即更新數據'):
        st.cache_data.clear()
        st.rerun()

    # 獲取數據
    with st.spinner('正在連線全球金融市場...'):
        yahoo_data = get_yahoo_data()
        sh_gold = get_shanghai_gold()
        usdt_cny = get_binance_usdt_cny()
        hibor = get_cnh_hibor() # 目前設為 None，因為 API 難抓
        
        # HIBOR Fallback UI 處理
        hibor_display = hibor if hibor else "N/A (需手動查詢)"
        hibor_val_for_logic = hibor if hibor else 2.5 # 預設給一個正常值以免邏輯壞掉

    if not yahoo_data:
        st.error("無法連接 Yahoo Finance，請檢查網絡。")
        return

    # 計算指標
    metrics = calculate_metrics(yahoo_data, sh_gold, usdt_cny)
    risk = analyze_risk(metrics, hibor_val_for_logic)

    # --- 戰情總結 (Action Center) ---
    st.markdown("---")
    st.subheader(f"當前戰略建議：{risk['msg']}")
    if risk['color'] == "red":
        st.error(risk['msg'])
    elif risk['color'] == "orange":
        st.warning(risk['msg'])
    elif risk['color'] == "purple":
        st.info(risk['msg'])
    else:
        st.success(risk['msg'])
    st.markdown("---")

    # --- 三大階段儀表板 ---
    col1, col2, col3 = st.columns(3)

    # 第一階段：潛伏期
    with col1:
        st.markdown("### 1. 潛伏期 (資金外逃)")
        
        # 黃金
        premium_val = metrics['gold_premium']
        p_color = "normal"
        if premium_val > 50: p_color = "inverse" # red
        
        st.metric(
            label="上海金價溢價 (USD/oz)",
            value=f"${premium_val:.2f}" if sh_gold else "N/A",
            delta="警戒值 > $30",
            delta_color="inverse" if premium_val > 30 else "normal",
            help="正值代表中國國內金價高於國際，資金搶購實物。"
        )
        if sh_gold:
            st.caption(f"SGE金價: ¥{metrics['sh_gold']}/g | 國際折算: ¥{(metrics['gold_intl_usd']/31.1035*metrics['cny']):.2f}/g")

        # USDT
        usdt_p = metrics['usdt_premium']
        st.metric(
            label="USDT 溢價 (Crypto)",
            value=f"{usdt_p:.2f}%" if usdt_cny else "N/A",
            delta="警戒值 > 2%",
            delta_color="inverse" if usdt_p > 2 else "normal",
            help="地下資金通道擁擠程度。"
        )
        if usdt_cny:
            st.caption(f"Binance P2P: ¥{metrics['usdt_cny']} | 基準匯率: ¥{metrics['cnh']:.4f}")

        # 港幣
        st.metric(
            label="港幣匯率 (USD/HKD)",
            value=f"{metrics['hkd']:.4f}",
            delta="弱方保證 7.85",
            delta_color="off" if metrics['hkd'] < 7.84 else "inverse"
        )

    # 第二階段：防守期
    with col2:
        st.markdown("### 2. 防守期 (央行博弈)")
        
        # CNH
        st.metric(
            label="離岸人民幣 (CNH)",
            value=f"{metrics['cnh']:.4f}",
            delta="關鍵位 7.35",
            delta_color="inverse" if metrics['cnh'] > 7.30 else "normal"
        )

        # Spread
        spr = metrics['spread']
        st.metric(
            label="在離岸價差 (Spread)",
            value=f"{spr:.0f} pips",
            delta="警戒值 > 500",
            delta_color="inverse" if spr > 500 else "normal",
            help="正值越大，代表海外做空力量越強。"
        )
        st.caption(f"CNY (在岸): {metrics['cny']:.4f}")

        # HIBOR
        st.metric(
            label="離岸資金成本 (HIBOR O/N)",
            value=hibor_display,
            delta="警戒值 > 5%",
            delta_color="off", # 無法自動判斷顏色因為可能是文字
            help="若飆升代表央行抽銀根夾殺空頭。"
        )

    # 第三階段：操作期
    with col3:
        st.markdown("### 3. 操作期 (扣板機)")
        
        # 簡單的技術判斷
        rsi_mock = "計算中..." # 這裡可以用 pandas ta lib 計算，為簡化先略過
        
        st.markdown("**操作檢核表：**")
        
        check_1 = metrics['cnh'] > 7.30
        check_2 = metrics['spread'] > 500
        check_3 = metrics['gold_premium'] > 30
        
        st.checkbox("CNH 突破 7.30", value=check_1, disabled=True)
        st.checkbox("價差擴大 > 500點", value=check_2, disabled=True)
        st.checkbox("黃金/USDT 異常溢價", value=check_3, disabled=True)
        
        if check_1 and check_2:
            st.error("🚨 趨勢確立：建議執行資產美元化")
        else:
            st.info("✋ 條件未滿足：保持觀望")

    st.markdown("---")
    st.caption(f"最後更新時間: {metrics['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
    st.caption("免責聲明：此工具透過爬蟲獲取數據，若網站改版可能會導致部分數值顯示 N/A。請以專業看盤軟體為準。")

if __name__ == "__main__":
    main()