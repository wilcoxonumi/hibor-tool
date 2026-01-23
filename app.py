import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
from datetime import date

# === 0. [新增] 字体设置 (解决图例中文显示问题) ===
# 尝试设置中文字体，解决 matplotlib 默认无法显示中文的问题
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS', 'sans-serif'] 
plt.rcParams['axes.unicode_minus'] = False # 解决负号显示为方块的问题

# === 1. 页面基本配置 ===
st.set_page_config(page_title="HKMA 数据", layout="wide")
st.title("🇭🇰 HKMA 金融数据提取工具")

# === 2. 定义数据源配置 (已修正：只保留3个接口) ===
API_CONFIG = {
    "HIBOR (香港银行同业拆息)": {
        "url": "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily",
        "segment": "hibor.fixing",
        "date_col": "end_of_day",
        "title_en": "HIBOR Interest Rates - Daily",
        "doc_url": "https://apidocs.hkma.gov.hk/gb_chi/documentation/market-data-and-statistics/monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily/"
    },
    "RMB Deposit Rates (人民币存款利率)": {
        "url": "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/renminbi-dr",
        "segment": None,
        "date_col": "end_of_month",
        "title_en": "RMB Deposit Rates",
        "doc_url": "https://apidocs.hkma.gov.hk/gb_chi/documentation/market-data-and-statistics/monthly-statistical-bulletin/er-ir/renminbi-dr/"
    },
    "Monetary Statistics (货币统计)": {
        "url": "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/financial/monetary-statistics",
        "segment": None,
        "date_col": "end_of_month",
        "title_en": "Monetary Statistics (M1/M2/M3)",
        "doc_url": "https://apidocs.hkma.gov.hk/gb_chi/documentation/market-data-and-statistics/monthly-statistical-bulletin/financial/monetary-statistics/"
    }
}

# === 3. 读取 CSV 配置 ===
@st.cache_data
def load_variable_meta():
    try:
        # 直接读取标准 CSV
        df_meta = pd.read_csv("variable_config.csv")
        # 去重
        df_meta = df_meta.drop_duplicates(subset=['variable'])
        # 转字典
        return df_meta.set_index('variable').to_dict(orient='index')
    except Exception as e:
        st.warning("⚠️ 提示: 目录下没有找到 variable_config.csv，将显示原始英文代码。")
        return {}

VARIABLE_META = load_variable_meta()

def get_display_info(var_name):
    """获取变量的中文名和单位"""
    info = VARIABLE_META.get(var_name, {"label": var_name, "unit": ""})
    if pd.isna(info.get('unit')): info['unit'] = ""
    if pd.isna(info.get('label')): info['label'] = var_name
    return info

# === 4. 初始化 Session State ===
if 'df_all' not in st.session_state:
    st.session_state['df_all'] = None
if 'current_source' not in st.session_state:
    st.session_state['current_source'] = ""

# === 5. 侧边栏：控制面板 ===
with st.sidebar:
    st.header("1. 数据源设置")
    
    selected_source_name = st.selectbox("选择数据类型", options=list(API_CONFIG.keys()))
    current_config = API_CONFIG[selected_source_name]
    
    st.divider()
    st.info(f"设置 {selected_source_name} 的抓取范围")
    
    earliest_date = date(1990, 1, 1)
    default_start = date(date.today().year - 1, 1, 1)
    
    fetch_start = st.date_input("抓取开始日期", value=default_start, min_value=earliest_date, max_value=date.today())
    fetch_end = st.date_input("抓取结束日期", value=date.today(), min_value=earliest_date, max_value=date.today())
    
    fetch_btn = st.button("🚀 点击提取数据", type="primary")

# === 6. 数据提取函数 ===
@st.cache_data
def fetch_hkma_data(api_url, segment, start_str, end_str):
    pagesize = 1000
    offset = 0
    all_records = []
    placeholder = st.empty()
    target_start = pd.to_datetime(start_str)
    target_end = pd.to_datetime(end_str)
    
    while True:
        placeholder.text(f"正在读取 HKMA 接口... Offset: {offset}")
        params = {"pagesize": pagesize, "offset": offset, "from": start_str, "to": end_str}
        if segment: params["segment"] = segment
            
        try:
            response = requests.get(api_url, params=params)
            response.raise_for_status()
            data = response.json()
            records = data.get("result", {}).get("records", [])
            if not records: break
            all_records.extend(records)
            offset += pagesize
        except Exception as e:
            st.error(f"API 请求失败: {e}")
            break
            
    placeholder.empty()
    if not all_records: return pd.DataFrame()
    
    df = pd.DataFrame(all_records)
    
    # 清洗日期
    date_col_found = None
    possible_date_cols = ['end_of_day', 'end_of_month', 'date', 'observation_date']
    for col in possible_date_cols:
        if col in df.columns:
            date_col_found = col
            break
            
    if date_col_found:
        df[date_col_found] = pd.to_datetime(df[date_col_found], errors='coerce')
        df = df.dropna(subset=[date_col_found])
        mask = (df[date_col_found] >= target_start) & (df[date_col_found] <= target_end)
        df = df.loc[mask].sort_values(date_col_found)
