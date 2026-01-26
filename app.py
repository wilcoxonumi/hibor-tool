import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm # <--- 引入字体管理器
import os
from datetime import date
import matplotlib.ticker as mticker

# === 1. 页面基本配置 ===
st.set_page_config(page_title="HKMA 数据", layout="wide")
st.title("HKMA 金融数据提取工具")

# === 2. 定义数据源配置 ===
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
        "title_en": "Monetary Statistics",
        "doc_url": "https://apidocs.hkma.gov.hk/gb_chi/documentation/market-data-and-statistics/monthly-statistical-bulletin/financial/monetary-statistics/"
    }
}

# === 3. 读取 CSV 配置 ===
@st.cache_data
def load_variable_meta():
    try:
        df_meta = pd.read_csv("variable_config.csv")
        df_meta = df_meta.drop_duplicates(subset=['variable'])
        return df_meta.set_index('variable').to_dict(orient='index')
    except Exception:
        return {}

VARIABLE_META = load_variable_meta()

def get_display_info(var_name):
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
    fetch_btn = st.button("点击提取数据", type="primary")

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
        
    return df

# === 7. 执行提取逻辑 ===
if fetch_btn:
    if st.session_state['current_source'] != selected_source_name:
        st.session_state['df_all'] = None
        st.session_state['current_source'] = selected_source_name
        if 'plot_start' in st.session_state: del st.session_state.plot_start
        if 'plot_end' in st.session_state: del st.session_state.plot_end

    with st.spinner(f'正在获取 {selected_source_name} 数据...'):
        df_new = fetch_hkma_data(
            current_config['url'],
            current_config['segment'],
            fetch_start.strftime("%Y-%m-%d"),
            fetch_end.strftime("%Y-%m-%d")
        )
        
        if not df_new.empty:
            date_col_found = None
            possible_date_cols = ['end_of_day', 'end_of_month', 'date']
            for col in possible_date_cols:
                if col in df_new.columns:
                    date_col_found = col
                    break
            if date_col_found:
                df_new['date_obj'] = df_new[date_col_found]
                st.session_state['df_all'] = df_new
                st.success(f"成功获取了 {len(df_new)} 条记录。")
            else:
                st.error("未找到日期列。")
        else:
            st.warning("未找到数据，请检查日期范围。")

# === 8. 主界面展示 ===
if st.session_state['df_all'] is not None:
    df = st.session_state['df_all']
    current_config = API_CONFIG[st.session_state['current_source']]
    
    st.divider()
    
    # --- 下载模块 ---
    st.header(f"2. 数据下载: {st.session_state['current_source']}")
    if "doc_url" in current_config:
        st.markdown(f" **数据定义与来源:** [点击查看 HKMA 官方字段说明文档]({current_config['doc_url']})")
    
    col_d1, col_d2 = st.columns([1, 4])
    with col_d1:
        df_download = df.copy()
        date_col_name = current_config.get('date_col', 'end_of_day')
        date_format = '%Y-%m' if 'month' in date_col_name.lower() else '%Y-%m-%d'
        
        if date_col_name in df_download.columns:
            df_download[date_col_name] = df_download[date_col_name].dt.strftime(date_format)
        if 'date_obj' in df_download.columns:
            df_download = df_download.drop(columns=['date_obj'])

        csv = df_download.to_csv(index=False, encoding="utf-8-sig").encode('utf-8-sig')
        file_name = f"hkma_data_{fetch_start}_{fetch_end}.csv"
        st.download_button(" 下载 CSV", csv, file_name, "text/csv")
    
    with col_d2:
        with st.expander(" 预览数据 & 字段说明"):
            st.subheader("前 5 行数据")
            st.dataframe(df_download.head())
            st.subheader("字段说明")
            meta_data_list = []
            for col in df_download.columns:
                if col in VARIABLE_META:
                    info = VARIABLE_META[col]
                    meta_data_list.append({"原始变量": col, "中文描述": info['label'], "单位": info['unit']})
            if meta_data_list: st.table(pd.DataFrame(meta_data_list))

    # --- 作图模块 ---
    st.header("3. 作图")
    
    # 1. 引入必要的库
    import matplotlib.ticker as mticker
    import os
    import matplotlib.font_manager as fm

    # 2. 列筛选逻辑
    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    exclude_keywords = ['id', 'year', 'month', 'day', 'rec_count']
    plot_options = [c for c in numeric_cols if not any(k in c.lower() for k in exclude_keywords)]
    
    # 兜底：如果没筛出来，就排除掉日期列剩下的都算
    if not plot_options:
         plot_options = [c for c in df.columns if c != 'date_obj' and c not in ['end_of_day', 'end_of_month']]

    # 3. 日期滑块与输入框的双向同步
    min_d, max_d = df['date_obj'].min().date(), df['date_obj'].max().date()
    
    # 初始化 Session State
    if 'plot_start' not in st.session_state or st.session_state.plot_start < min_d: 
        st.session_state.plot_start = min_d
    if 'plot_end' not in st.session_state or st.session_state.plot_end > max_d: 
        st.session_state.plot_end = max_d
        
    # 回调函数
    def update_inputs(): 
        st.session_state.plot_start, st.session_state.plot_end = st.session_state.slider_range
    def update_slider(): 
        st.session_state.slider_range = (st.session_state.plot_start, st.session_state.plot_end)

    # 4. 布局控制
    col_sel, col_date1, col_date2 = st.columns([2, 1, 1])
    with col_sel:
        selected_vars = st.multiselect(
            "选择变量 (Y轴)",
            options=plot_options,
            format_func=lambda x: f"{get_display_info(x)['label']} ({x})", # 显示中文 Label
            default=plot_options[:2] if len(plot_options) >= 2 else plot_options
        )
    with col_date1: 
        st.date_input("开始日期", key="plot_start", min_value=min_d, max_value=max_d, on_change=update_slider)
    with col_date2: 
        st.date_input("结束日期", key="plot_end", min_value=min_d, max_value=max_d, on_change=update_slider)
    
    st.slider(
        "快速拖拽区间", 
        min_value=min_d, 
        max_value=max_d, 
        value=(st.session_state.plot_start, st.session_state.plot_end), 
        key="slider_range", 
        on_change=update_inputs
    )

    # 5. 开始作图
    if selected_vars:
        current_start, current_end = st.session_state.plot_start, st.session_state.plot_end
        mask = (df['date_obj'].dt.date >= current_start) & (df['date_obj'].dt.date <= current_end)
        plot_df = df.loc[mask]
        
        if plot_df.empty:
            st.warning("该时段无数据。")
        else:
            fig, ax = plt.subplots(figsize=(12, 6)) # 高度稍微增加一点
            
            # === A. 智能分拣: 谁走左轴，谁走右轴 (适配中文配置) ===
            primary_vars = []   # 左轴 (通常是金额)
            secondary_vars = [] # 右轴 (通常是利率)
            
            for col in selected_vars:
                info = get_display_info(col)
                # 安全获取字符串并转小写
                unit = str(info.get('unit', '')).lower()
                label = str(info.get('label', '')).lower()
                
                # 判断规则: 如果单位包含 '年率'/'%' 或 名字包含 '利率'/'hibor'/'汇率'/'指数'
                is_rate = (
                    '年率' in unit or 
                    '%' in unit or 
                    '利率' in label or 
                    '收益率' in label or 
                    '汇率' in label or 
                    'hibor' in label or
                    '指数' in label
                )
                
                if is_rate:
                    secondary_vars.append(col)
                else:
                    primary_vars.append(col)
            
            # 特殊情况处理：如果全是利率，或者全是金额，就强制用单轴 (没必要双轴)
            if not primary_vars and secondary_vars:
                primary_vars = secondary_vars
                secondary_vars = []
            
            # === B. 字体加载 (本地文件优先) ===
            my_font = None
            font_path = "SimHei.ttf" # 确保 SimHei.ttf 在同级目录下
            if os.path.exists(font_path):
                my_font = fm.FontProperties(fname=font_path)
            else:
                # 本地调试回退方案
                plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'sans-serif']

            # === C. 辅助绘图函数 (统一画线逻辑) ===
            def plot_lines(axes, vars_list, is_secondary=False):
                lines = []
                for col in vars_list:
                    series = pd.to_numeric(plot_df[col], errors='coerce')
                    info = get_display_info(col)
                    
                    # 图例显示: 双轴时右轴加个标记
                    axis_tag = "(右轴)" if is_secondary else ""
                    legend_label = f"{info['label']} {axis_tag}"
                    # 只有当单位不为空时才显示单位
                    if info['unit']: 
                        legend_label += f" ({info['unit']})"
                    
                    # 右轴用虚线，左轴用实线，方便区分
                    linestyle = '--' if is_secondary else '-' 
                    
                    line, = axes.plot(
                        plot_df['date_obj'], 
                        series, 
                        label=legend_label, 
                        linewidth=1.5, 
                        linestyle=linestyle
                    )
                    lines.append(line)
                return lines

            # === D. 执行画图 ===
            
            # 1. 画左轴
            lines_1 = plot_lines(ax, primary_vars, is_secondary=False)
            # ax.set_ylabel("金额 / 数值", fontproperties=my_font) # 可选：设置左轴标签

            # 2. 画右轴 (如果有的话)
            lines_2 = []
            if secondary_vars:
                ax2 = ax.twinx() # 创建共享X轴的第二个Y轴
                lines_2 = plot_lines(ax2, secondary_vars, is_secondary=True)
                # ax2.set_ylabel("利率 (%)", fontproperties=my_font) # 可选：设置右轴标签
                
                # 右轴格式化: 强制保留2位小数 (4.50)
                ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, p: f"{x:.2f}"))
            
            # === E. 统一图例 (把左右轴的线合在一个图例框里) ===
            all_lines = lines_1 + lines_2
            all_labels = [l.get_label() for l in all_lines]
            
            if my_font:
                ax.legend(all_lines, all_labels, prop=my_font, loc='upper left')
                ax.set_title(current_config.get('title_en', 'Data Trends'), fontproperties=my_font)
            else:
                ax.legend(all_lines, all_labels, loc='upper left')
                ax.set_title(current_config.get('title_en', 'Data Trends'))

            # === F. 左轴格式化 (千分位 + 智能小数) ===
            def human_format_left(x, pos):
                # 0 就显示 0
                if x == 0: return "0"
                # 小数 (如 HIBOR 单轴显示时)，保留2位
                if abs(x) < 1000: return f"{x:.2f}"
                # 大数 (如 M1)，用千分位逗号，不带小数
                return f"{x:,.0f}"
            
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(human_format_left))
            
            ax.grid(True, linestyle=':', alpha=0.6)
            st.pyplot(fig)
    else:
        st.info("请选择变量。")

elif not fetch_btn:
    st.info("👈 请先在左侧提取数据。")
