import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
from datetime import date

# === 1. 页面基本配置 ===
st.set_page_config(page_title="HKMA 金融数据看板", layout="wide")
st.title("🇭🇰 HKMA 金融数据提取与分析工具")

# === 2. 定义数据源配置 (核心修改点) ===
# 以后如果想加新数据，就在这里加一行
API_CONFIG = {
    "HIBOR (香港银行同业拆息)": {
        "url": "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily",
        "segment": "hibor.fixing",
        "date_col": "end_of_day",  # HIBOR API 返回的日期列名
        "prefix": "ir"             # 用于识别数据列的前缀 (ir_1m, ir_3m...)
    },
    "RMB Deposit Rates (人民币存款利率)": {
        "url": "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/renminbi-dr",
        "segment": None,           # 这个API可能不需要segment参数，或者视具体文档而定
        "date_col": "end_of_month", # 注意：存款利率通常是月度数据，日期列名可能不同
        "prefix": "sav"            # 假设存款列包含 sav (savings) 或 term，稍后我们用自动识别
    }
}

# === 3. 初始化 Session State ===
if 'df_all' not in st.session_state:
    st.session_state['df_all'] = None
if 'current_source' not in st.session_state:
    st.session_state['current_source'] = ""

# === 4. 侧边栏：控制面板 ===
with st.sidebar:
    st.header("1. 数据源设置")
    
    # [新增] 数据类型选择器
    selected_source_name = st.selectbox(
        "选择数据类型",
        options=list(API_CONFIG.keys())
    )
    
    # 获取当前选中的配置
    current_config = API_CONFIG[selected_source_name]
    
    st.divider()
    
    st.info(f"设置 {selected_source_name} 的抓取范围")
    
    # 默认抓取过去一年的数据
    default_start = date(date.today().year - 1, 1, 1)
    fetch_start = st.date_input("抓取开始日期", default_start)
    fetch_end = st.date_input("抓取结束日期", date.today())
    
    # 按钮
    fetch_btn = st.button("🚀 点击提取数据", type="primary")

# === 5. 通用数据提取函数 ===
@st.cache_data
def fetch_hkma_data(api_url, segment, start_str, end_str):
    pagesize = 1000 # 如果数据量大，可以调大
    offset = 0
    all_records = []
    
    placeholder = st.empty()
    
    while True:
        placeholder.text(f"正在读取 HKMA 接口... Offset: {offset}")
        
        # 构建 URL，根据是否有 segment 参数动态调整
        params_str = f"?from={start_str}&to={end_str}&pagesize={pagesize}&offset={offset}"
        if segment:
            params_str += f"&segment={segment}"
            
        full_url = api_url + params_str
        
        try:
            response = requests.get(full_url)
            response.raise_for_status()
            data = response.json()
            records = data.get("result", {}).get("records", [])
            
            if not records:
                break
            all_records.extend(records)
            offset += pagesize
        except Exception as e:
            st.error(f"API 请求失败: {e}")
            break
            
    placeholder.empty()
    
    if not all_records:
        return pd.DataFrame()
    
    df = pd.DataFrame(all_records)
    return df

# === 6. 处理按钮逻辑 ===
if fetch_btn:
    # 如果切换了数据源，清除旧缓存
    if st.session_state['current_source'] != selected_source_name:
        st.session_state['df_all'] = None
        st.session_state['current_source'] = selected_source_name

    with st.spinner(f'正在获取 {selected_source_name} 数据...'):
        df_new = fetch_hkma_data(
            current_config['url'],
            current_config['segment'],
            fetch_start.strftime("%Y-%m-%d"),
            fetch_end.strftime("%Y-%m-%d")
        )
        
        if not df_new.empty:
            # 自动标准化日期列：不管API返回 end_of_day 还是 end_of_month，都统一复制为 'date_obj' 用于作图
            # 尝试查找可能的日期列名
            date_col_found = None
            possible_date_cols = ['end_of_day', 'end_of_month', 'date', 'observation_date']
            
            for col in possible_date_cols:
                if col in df_new.columns:
                    date_col_found = col
                    break
            
            if date_col_found:
                df_new['date_obj'] = pd.to_datetime(df_new[date_col_found])
                df_new = df_new.sort_values('date_obj')
                st.session_state['df_all'] = df_new
                st.success(f"成功！获取了 {len(df_new)} 条记录。")
            else:
                st.error(f"数据提取成功，但未找到日期列。可用列名: {list(df_new.columns)}")
        else:
            st.warning("未找到数据，请检查日期范围或网络。")

# === 7. 主界面展示 ===
if st.session_state['df_all'] is not None:
    df = st.session_state['df_all']
    
    st.divider()
    
    # --- 下载模块 ---
    st.header(f"2. 数据下载: {st.session_state['current_source']}")
    
    col_d1, col_d2 = st.columns([1, 4])
    with col_d1:
        csv = df.to_csv(index=False, encoding="utf-8-sig").encode('utf-8-sig')
        file_name = f"hkma_data_{fetch_start}_{fetch_end}.csv"
        st.download_button("📥 下载 CSV", csv, file_name, "text/csv")
    
    with col_d2:
        with st.expander("预览数据"):
            st.dataframe(df.head())

    st.divider()

    # --- 作图模块 ---
    st.header("3. 交互式分析")
    
    # 智能列过滤：排除掉 ID, Date 等非数值列
    # 我们只保留 float/int 类型的列，且排除掉常见的 ID 列
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    exclude_keywords = ['id', 'year', 'month', 'day', 'rec_count']
    plot_options = [c for c in numeric_cols if not any(k in c.lower() for k in exclude_keywords)]
    
    # 如果没找到数值列（万一所有都是字符串），尝试找所有非日期列
    if not plot_options:
        plot_options = [c for c in df.columns if c != 'date_obj' and c != date_col_found]

    c1, c2 = st.columns(2)
    with c1:
        selected_vars = st.multiselect(
            "选择变量 (Y轴)",
            options=plot_options,
            default=plot_options[:2] if len(plot_options) >= 2 else plot_options # 默认选前两个
        )
    with c2:
        min_d, max_d = df['date_obj'].min().date(), df['date_obj'].max().date()
        plot_dates = st.slider("时间区间 (X轴)", min_d, max_d, (min_d, max_d))

    # 作图执行
    if selected_vars:
        # 筛选
        mask = (df['date_obj'].dt.date >= plot_dates[0]) & (df['date_obj'].dt.date <= plot_dates[1])
        plot_df = df.loc[mask]
        
        fig, ax = plt.subplots(figsize=(12, 5))
        
        for col in selected_vars:
            # 强制转为数字，处理可能的非数字字符
            series = pd.to_numeric(plot_df[col], errors='coerce')
            ax.plot(plot_df['date_obj'], series, label=col, marker='o', markersize=3)
            
        ax.set_title(f"{st.session_state['current_source']} 走势")
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.6)
        st.pyplot(fig)
    else:
        st.info("请选择至少一个变量进行作图。")

elif not fetch_btn:
    st.info("👈 请在左侧选择数据类型并提取数据。")