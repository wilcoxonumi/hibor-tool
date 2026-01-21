
import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
from datetime import date

# === 1. 页面配置 ===
st.set_page_config(page_title="HKMA HIBOR提取", layout="wide")
st.title("HIBOR 数据提取与作图")

# === 2. 初始化 Session State (关键步骤) ===
# 用于在此时刻保存数据，防止用户调整作图选项时数据丢失
if 'df_all' not in st.session_state:
    st.session_state['df_all'] = None

# === 3. 左侧：数据源控制 (Source Control) ===
with st.sidebar:
    st.header("1. 数据源设置")
    st.info("设置从 HKMA 服务器抓取的总时间范围")
    
    # 默认抓取过去一年的数据
    default_start = date(date.today().year - 1, 1, 1)
    fetch_start = st.date_input("抓取开始日期", default_start)
    fetch_end = st.date_input("抓取结束日期", date.today())
    
    fetch_btn = st.button("点击提取数据", type="primary")

# === 4. 数据提取函数 (保持不变) ===
@st.cache_data
def fetch_hkma_data(start_str, end_str):
    pagesize = 1000
    offset = 0
    all_records = []
    
    placeholder = st.empty() # 占位符用于显示进度
    
    while True:
        placeholder.text(f"正在下载... Offset: {offset}")
        url = (
            "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily"
            f"?segment=hibor.fixing&from={start_str}&to={end_str}&pagesize={pagesize}&offset={offset}"
        )
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            records = data.get("result", {}).get("records", [])
            
            if not records:
                break
            all_records.extend(records)
            offset += pagesize
        except Exception as e:
            st.error(f"API 错误: {e}")
            break
            
    placeholder.empty()
    
    if not all_records:
        return pd.DataFrame()
    
    df = pd.DataFrame(all_records)
    df["end_of_day"] = pd.to_datetime(df["end_of_day"])
    return df.sort_values("end_of_day")

# === 5. 处理按钮点击 ===
if fetch_btn:
    with st.spinner('正在连接 HKMA 数据库...'):
        # 转换日期格式
        s_str = fetch_start.strftime("%Y-%m-%d")
        e_str = fetch_end.strftime("%Y-%m-%d")
        
        # 获取数据并存入 session_state
        fetched_df = fetch_hkma_data(s_str, e_str)
        
        if not fetched_df.empty:
            st.session_state['df_all'] = fetched_df
            st.success(f"数据提取成功！共 {len(fetched_df)} 条记录。")
        else:
            st.warning("未找到数据，请检查日期范围。")

# === 6. 主界面：数据展示与作图 (仅当有数据时显示) ===
if st.session_state['df_all'] is not None:
    df = st.session_state['df_all']
    
    st.divider() # 分割线
    
    # --- 模块 A: 下载全量数据 ---
    st.header("2. 数据下载")
    col1, col2 = st.columns([1, 3])
    with col1:
        csv = df.to_csv(index=False, encoding="utf-8-sig").encode('utf-8-sig')
        file_name = f"hibor_raw_{df['end_of_day'].min().date()}_{df['end_of_day'].max().date()}.csv"
        
        st.download_button(
            label="📥 下载全量 CSV",
            data=csv,
            file_name=file_name,
            mime='text/csv',
            help="下载包含所选时间范围内所有变量的原始数据"
        )
    with col2:
        with st.expander("预览原始数据 (前 5 行)"):
            st.dataframe(df.head())

    st.divider()

    # --- 模块 B: 交互式作图 ---
    st.header("3. 交互式分析图表")
    
    # B1. 筛选控制器
    st.subheader("图表设置")
    c1, c2 = st.columns(2)
    
    with c1:
        # 获取所有以 ir_ 开头的列作为可选项
        available_cols = [c for c in df.columns if c.startswith('ir_')]
        
        # 变量选择器
        selected_vars = st.multiselect(
            "选择要作图的变量 (Variables)",
            options=available_cols,
            default=["ir_1m", "ir_3m"], # 默认选中 1M 和 3M
            format_func=lambda x: x.upper().replace("_", " ") # 让显示更好看 (ir_1m -> IR 1M)
        )
        
    with c2:
        # 日期范围选择器 (限制在已下载的数据范围内)
        min_date = df['end_of_day'].min().date()
        max_date = df['end_of_day'].max().date()
        
        plot_dates = st.slider(
            "选择作图的时间区间",
            min_value=min_date,
            max_value=max_date,
            value=(min_date, max_date) # 默认全选
        )
    
    # B2. 根据设置筛选数据
    mask = (df['end_of_day'].dt.date >= plot_dates[0]) & (df['end_of_day'].dt.date <= plot_dates[1])
    plot_df = df.loc[mask]
    
    # B3. 开始作图
    if selected_vars:
        fig, ax = plt.subplots(figsize=(12, 5))
        
        for col in selected_vars:
            # 数据清洗：转为 float 并剔除空值
            series = pd.to_numeric(plot_df[col], errors='coerce')
            ax.plot(plot_df['end_of_day'], series, label=col.upper().replace("_", " "))
            
        ax.set_title(f"HIBOR Trends ({plot_dates[0]} to {plot_dates[1]})")
        ax.set_ylabel("Rate (%)")
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.7)
        
        st.pyplot(fig)
    else:
        st.info("请在上方至少选择一个变量进行作图。")

elif not fetch_btn:
    st.info("请在左侧侧边栏设置日期并点击“提取数据”开始。")
