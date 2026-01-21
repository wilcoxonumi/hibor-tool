import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
from datetime import date

# === 1. 页面基本配置 ===
st.set_page_config(page_title="HKMA 数据", layout="wide")
st.title("HKMA 金融数据提取工具")

# === 2. 定义数据源配置 (核心修改点) ===
# 以后如果想加新数据，就在这里加一行
API_CONFIG = {
    "HIBOR (香港银行同业拆息)": {
        "url": "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily",
        "segment": "hibor.fixing",
        "date_col": "end_of_day",  # HIBOR API 返回的日期列名
        "prefix": "ir",             # 用于识别数据列的前缀 (ir_1m, ir_3m...)
        "title_en": "HIBOR Interest Rates - Daily"
    },
    "RMB Deposit Rates (人民币存款利率)": {
        "url": "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/er-ir/renminbi-dr",
        "segment": None,           # 这个API可能不需要segment参数，或者视具体文档而定
        "date_col": "end_of_month", # 注意：存款利率通常是月度数据，日期列名可能不同
        "prefix": "sav",            # 假设存款列包含 sav (savings) 或 term，稍后我们用自动识别
        "title_en": "RMB Deposit Rates"
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
    
    # === 关键设置 ===
    # 1. 定义最早允许选到的日期 (比如 1990年，打破默认的10年限制)
    earliest_date = date(1990, 1, 1)
    
    # 2. 定义默认显示的日期 (保持你想要的“过去一年”)
    default_start = date(date.today().year - 1, 1, 1)
    
    # 3. 应用到输入框
    fetch_start = st.date_input(
        "抓取开始日期", 
        value=default_start,     # <--- 默认显示：去年 (User Experience Good)
        min_value=earliest_date, # <--- 允许翻页：直到 1990 (Capability Good)
        max_value=date.today()
    )
    
    fetch_end = st.date_input(
        "抓取结束日期", 
        value=date.today(),
        min_value=earliest_date,
        max_value=date.today()
    )
    
    # 按钮
    fetch_btn = st.button("点击提取数据", type="primary")

# === 5. 通用数据提取函数 (修复版) ===
@st.cache_data
def fetch_hkma_data(api_url, segment, start_str, end_str):
    pagesize = 1000 # 如果数据量大，可以调大
    offset = 0
    all_records = []
    
    placeholder = st.empty()
    
    # 将字符串日期转为 datetime 对象，用于后续的 Python 端强制过滤
    # 这是解决“日期总是从最早开始”的关键步骤
    target_start = pd.to_datetime(start_str)
    target_end = pd.to_datetime(end_str)
    
    while True:
        placeholder.text(f"正在读取 HKMA 接口... Offset: {offset}")
        
        # 【优化】使用 params 字典代替手动拼字符串，更加稳定且防错
        params = {
            "pagesize": pagesize,
            "offset": offset,
            "from": start_str,
            "to": end_str
        }
        if segment:
            params["segment"] = segment
            
        try:
            # requests 库会自动将 params 拼接到 URL 后面
            response = requests.get(api_url, params=params)
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
    
    # === 关键修复：Python 端强制二次过滤 ===
    # 就算 API 返回了 1990 年的数据，这里也会在本地把它删掉
    
    # 1. 自动寻找日期列 (适配 HIBOR 和 存款利率)
    date_col_found = None
    possible_date_cols = ['end_of_day', 'end_of_month', 'date', 'observation_date']
    for col in possible_date_cols:
        if col in df.columns:
            date_col_found = col
            break
            
    if date_col_found:
        # 2. 转为 datetime 格式
        df[date_col_found] = pd.to_datetime(df[date_col_found])
        
        # 3. 【核心步骤】强制删除范围外的数据
        mask = (df[date_col_found] >= target_start) & (df[date_col_found] <= target_end)
        df = df.loc[mask]
        
        # 4. 按日期排序 (保证图表线条连贯)
        df = df.sort_values(date_col_found)
        
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
        st.download_button("下载 CSV", csv, file_name, "text/csv")
    
    with col_d2:
        with st.expander("预览数据"):
            st.dataframe(df.head())

    st.divider()

    # --- 作图模块 ---
    st.header("3. 作图")
    
    # 1. 智能列过滤 (完整保留原逻辑)
    # 排除掉 ID, Date 等非数值列
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    exclude_keywords = ['id', 'year', 'month', 'day', 'rec_count']
    plot_options = [c for c in numeric_cols if not any(k in c.lower() for k in exclude_keywords)]
    
    # 兜底逻辑：如果没找到数值列，尝试找所有非日期列
    if not plot_options:
        # 这里做了一点小优化，确保也不包含我们生成的 date_obj
        plot_options = [c for c in df.columns if c != 'date_obj' and c not in ['end_of_day', 'end_of_month']]

    # 2. 获取数据的时间边界
    min_d, max_d = df['date_obj'].min().date(), df['date_obj'].max().date()

    # --- 新增：初始化 Session State 用于双向同步 ---
    if 'plot_start' not in st.session_state or st.session_state.plot_start < min_d:
        st.session_state.plot_start = min_d
    if 'plot_end' not in st.session_state or st.session_state.plot_end > max_d:
        st.session_state.plot_end = max_d
        
    # 回调函数：滑块拖动 -> 更新输入框
    def update_inputs_from_slider():
        st.session_state.plot_start = st.session_state.slider_range[0]
        st.session_state.plot_end = st.session_state.slider_range[1]

    # 回调函数：输入框修改 -> 更新滑块
    def update_slider_from_inputs():
        if st.session_state.plot_start > st.session_state.plot_end:
            st.error("开始日期不能晚于结束日期")
        # 同步给滑块的 key
        st.session_state.slider_range = (st.session_state.plot_start, st.session_state.plot_end)

    # 3. 布局调整：改成三栏 [变量选择(宽) | 开始日期 | 结束日期]
    col_sel, col_date1, col_date2 = st.columns([2, 1, 1])
    
    with col_sel:
        selected_vars = st.multiselect(
            "选择变量 (Y轴)",
            options=plot_options,
            default=plot_options[:2] if len(plot_options) >= 2 else plot_options
        )
    
    with col_date1:
        st.date_input(
            "开始日期",
            key="plot_start",
            min_value=min_d,
            max_value=max_d,
            on_change=update_slider_from_inputs # 绑定回调
        )
        
    with col_date2:
        st.date_input(
            "结束日期",
            key="plot_end",
            min_value=min_d,
            max_value=max_d,
            on_change=update_slider_from_inputs # 绑定回调
        )

    # 4. 布局：下方长滑块 (快速拖拽)
    st.slider(
        "快速拖拽调整区间",
        min_value=min_d,
        max_value=max_d,
        value=(st.session_state.plot_start, st.session_state.plot_end),
        key="slider_range",
        on_change=update_inputs_from_slider # 绑定回调
    )

    # 5. 作图执行
    if selected_vars:
        # 使用 session_state 中的精确日期进行过滤
        current_start = st.session_state.plot_start
        current_end = st.session_state.plot_end
        
        mask = (df['date_obj'].dt.date >= current_start) & (df['date_obj'].dt.date <= current_end)
        plot_df = df.loc[mask]
        
        if plot_df.empty:
            st.warning("所选时间段内没有数据。")
        else:
            fig, ax = plt.subplots(figsize=(12, 5))
            
            for col in selected_vars:
                # 核心防错：强制转数字
                series = pd.to_numeric(plot_df[col], errors='coerce')
                # 核心修改：去掉 marker='o'，线条更平滑
                ax.plot(plot_df['date_obj'], series, label=col, linewidth=1.5)
                
            # 核心修改：使用英文标题 (从 API_CONFIG 读取)
            # 使用 .get 方法防止未来加了新API忘记写 title_en 导致报错
            current_config = API_CONFIG[st.session_state['current_source']]
            ax.set_title(current_config.get('title_en', 'Data Trends'))
            
            ax.legend()
            ax.grid(True, linestyle='--', alpha=0.6)
            st.pyplot(fig)
    else:
        st.info("请选择至少一个变量进行作图。")