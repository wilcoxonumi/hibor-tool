import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm 
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
    "Exchange Fund Bills & Notes (外汇基金票据及债券收益率)": {
        # 
        "url": "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/efbn/efbn-yield-daily",
        "segment": None, # 这个接口通常不需要 segment 参数
        "date_col": "end_of_day",
        "title_en": "Exchange Fund Bills & Notes Yields - Daily",
        "doc_url": "https://apidocs.hkma.gov.hk/gb_chi/documentation/market-data-and-statistics/monthly-statistical-bulletin/efbn/efbn-yield-daily/"
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
    },
    "Interbank Liquidity (银行同业流动资金)": {
        # === try 新增接口 ===
        "url": "https://api.hkma.gov.hk/public/market-data-and-statistics/daily-monetary-statistics/daily-figures-interbank-liquidity",
        "segment": None, 
        "date_col": "end_of_date",
        "title_en": "Interbank Liquidity - Daily",
        "doc_url": "https://apidocs.hkma.gov.hk/gb_chi/documentation/market-data-and-statistics/daily-monetary-statistics/daily-figures-interbank-liquidity/"
    },
    # === 新增：银行体系 (multiple api) ===
    "Banking Statistics (银行体系 - 综合数据)": {
        # 列表 List []，放多个 api
        "url": [
            # 3.2 客户存款 (按货币)
            "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/banking/customer-deposits-by-currency",
            # 3.3.1 客户存款 (按类别-港元及外币存款)
            "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/banking/customer-deposits-by-type-hkd-fc",
            # 3.6.1 资产质素-认可机构
            "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/banking/assetquality-ais",
            # 3.9.2 资产负债表-持牌银行
            "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/banking/balance-sheet-lb",
            # ... 在这里继续添加 3.5, 3.6 等链接 ...
        ],
        "segment": None,
        "date_col": "end_of_month", # check一下日期名
        "title_en": "Banking Statistics (Integrated)",
        "doc_url": "https://apidocs.hkma.gov.hk/gb_chi/documentation/market-data-and-statistics/monthly-statistical-bulletin/banking/"
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
    selected_source_name = st.selectbox("选择数据", options=list(API_CONFIG.keys()))
    current_config = API_CONFIG[selected_source_name]
    st.divider()
    
    # === 新增：强制清除缓存按钮  ===
    if st.button("强制清除缓存"):
        st.cache_data.clear()
        st.rerun()
    
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
    possible_date_cols = ['end_of_day', 'end_of_month', 'date', 'observation_date','end_of_date']
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

# === 7. 执行提取逻辑 (单接口 & 多接口自动合并) ===
if fetch_btn:
    # 1. 重置状态 (切换数据源时)
    if st.session_state['current_source'] != selected_source_name:
        st.session_state['df_all'] = None
        st.session_state['current_source'] = selected_source_name
        if 'plot_start' in st.session_state: del st.session_state.plot_start
        if 'plot_end' in st.session_state: del st.session_state.plot_end

    # 2. 准备抓取目标 (兼容 String 和 List)
    target_urls = current_config['url']
    if not isinstance(target_urls, list):
        target_urls = [target_urls] # 变成列表，方便处理

    final_df = pd.DataFrame()
    success_count = 0
    
    # 3. 进度提示
    progress_bar = st.progress(0)
    status_text = st.empty()

    with st.spinner(f'正在获取 {selected_source_name} 数据...'):
        
        for i, url in enumerate(target_urls):
            # 显示当前进度
            status_text.text(f"正在请求第 {i+1}/{len(target_urls)} 个接口...")
            
            # 调用原本的抓取函数
            df_part = fetch_hkma_data(
                url,
                current_config['segment'],
                fetch_start.strftime("%Y-%m-%d"),
                fetch_end.strftime("%Y-%m-%d")
            )
            
            if not df_part.empty:
                # 寻找日期列
                date_col_found = None
                possible_date_cols = ['end_of_day', 'end_of_month', 'date', 'end_of_date']
                for col in possible_date_cols:
                    if col in df_part.columns:
                        date_col_found = col
                        break
                
                if date_col_found:
                    # 建立统一的合并基准列 'date_obj'
                    df_part['date_obj'] = df_part[date_col_found]
                    
                    # === 核心合并逻辑 ===
                    if final_df.empty:
                        final_df = df_part
                    else:
                        # 按日期合并 (Outer Join 防止数据丢失)
                        # suffixes 处理重名列 (如 total_x, total_y)
                        final_df = pd.merge(final_df, df_part, on='date_obj', how='outer', suffixes=('', f'_{i}'))
                    
                    success_count += 1
            
            # 更新进度条
            progress_bar.progress((i + 1) / len(target_urls))

    # 4. 结果处理
    status_text.empty()
    progress_bar.empty()

    if not final_df.empty:
        # 按时间重新排序
        final_df = final_df.sort_values('date_obj')
        
        st.session_state['df_all'] = final_df
        st.success(f" 成功获取数据 (共合并 {success_count} 个接口，{len(final_df)} 行记录)")
    else:
        if success_count == 0:
            st.warning("未找到有效数据，请检查日期范围。")
        else:
            st.error("数据合并失败，请检查API返回格式。")

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

# --- 作图模块 (修复 id 误删 和 空格匹配) ---
    st.header("3. 作图")
    
    # 1. 引入库
    import matplotlib.ticker as mticker
    import os
    import matplotlib.font_manager as fm

    # 2. 列筛选逻辑
    
    # 2.1 强制转数字 (处理 "+0" 等字符串)
    ignore_cols = ['date_obj', 'end_of_day', 'end_of_month', 'end_of_date', 'date']
    for col in df.columns:
        if col not in ignore_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    
    # 2.2 排除逻辑 (关键修复：精确匹配 id)
    exclude_keywords = ['rec_count', 'rec_id'] 
    exclude_exact = ['year', 'month', 'day', 'id'] # 必须完全相等才排除
    
    plot_options = []
    for c in numeric_cols:
        c_lower = c.strip().lower() # 去空格再对比
        is_excluded = False
        
        # 规则 A: 包含特定垃圾关键词
        if any(k in c_lower for k in exclude_keywords): is_excluded = True
        # 规则 B: 精确等于某些词
        if c_lower in exclude_exact: is_excluded = True
        
        if not is_excluded:
            plot_options.append(c)
    
    # 
    if not plot_options:
         plot_options = [c for c in df.columns if c != 'date_obj' and c not in ['end_of_day', 'end_of_month', 'end_of_date']]

    # 3. 日期滑块与输入框的双向同步
    min_d, max_d = df['date_obj'].min().date(), df['date_obj'].max().date()
    
    if 'plot_start' not in st.session_state or st.session_state.plot_start < min_d: 
        st.session_state.plot_start = min_d
    if 'plot_end' not in st.session_state or st.session_state.plot_end > max_d: 
        st.session_state.plot_end = max_d
        
    def update_inputs(): st.session_state.plot_start, st.session_state.plot_end = st.session_state.slider_range
    def update_slider(): st.session_state.slider_range = (st.session_state.plot_start, st.session_state.plot_end)

    # 4. 布局
    col_sel, col_date1, col_date2 = st.columns([2, 1, 1])
    with col_sel:
        selected_vars = st.multiselect(
            "选择变量 (Y轴)",
            options=plot_options,
            format_func=lambda x: f"{get_display_info(x)['label']} ({x})",
            default=plot_options[:2] if len(plot_options) >= 2 else plot_options
        )
    with col_date1: st.date_input("开始日期", key="plot_start", min_value=min_d, max_value=max_d, on_change=update_slider)
    with col_date2: st.date_input("结束日期", key="plot_end", min_value=min_d, max_value=max_d, on_change=update_slider)
    st.slider("快速拖拽区间", min_value=min_d, max_value=max_d, value=(st.session_state.plot_start, st.session_state.plot_end), key="slider_range", on_change=update_inputs)

    # 5. 开始作图
    if selected_vars:
        current_start, current_end = st.session_state.plot_start, st.session_state.plot_end
        mask = (df['date_obj'].dt.date >= current_start) & (df['date_obj'].dt.date <= current_end)
        plot_df = df.loc[mask]
        
        if plot_df.empty:
            st.warning("该时段无数据。")
        else:
            fig, ax = plt.subplots(figsize=(12, 6))
            
            # === A. 这里加个 strip 以防万一 ===
            primary_vars = []
            secondary_vars = []
            
            for col in selected_vars:
                info = get_display_info(col)
                unit = str(info.get('unit', '')).lower()
                label = str(info.get('label', '')).lower()
                
                is_rate = ('年率' in unit or '%' in unit or '利率' in label or '收益率' in label or '汇率' in label or 'hibor' in label or '指数' in label)
                
                if is_rate: secondary_vars.append(col)
                else: primary_vars.append(col)
            
            if not primary_vars and secondary_vars:
                primary_vars = secondary_vars
                secondary_vars = []
            
            # === B. 字体与绘图 ===
            my_font = None
            font_path = "SimHei.ttf"
            if os.path.exists(font_path): my_font = fm.FontProperties(fname=font_path)
            else: plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'sans-serif']

            def plot_lines(axes, vars_list, is_secondary=False):
                lines = []
                for col in vars_list:
                    series = pd.to_numeric(plot_df[col], errors='coerce')
                    info = get_display_info(col)
                    axis_tag = "(右轴)" if is_secondary else ""
                    legend_label = f"{info['label']} {axis_tag}"
                    if info['unit']: legend_label += f" ({info['unit']})"
                    linestyle = '--' if is_secondary else '-'
                    line, = axes.plot(plot_df['date_obj'], series, label=legend_label, linewidth=1.5, linestyle=linestyle)
                    lines.append(line)
                return lines

            lines_1 = plot_lines(ax, primary_vars, is_secondary=False)
            lines_2 = []
            if secondary_vars:
                ax2 = ax.twinx()
                lines_2 = plot_lines(ax2, secondary_vars, is_secondary=True)
                ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, p: f"{x:.2f}"))
            
            all_lines = lines_1 + lines_2
            all_labels = [l.get_label() for l in all_lines]
            
            if my_font:
                ax.legend(all_lines, all_labels, prop=my_font, loc='upper left')
                ax.set_title(current_config.get('title_en', 'Data Trends'), fontproperties=my_font)
            else:
                ax.legend(all_lines, all_labels, loc='upper left')
                ax.set_title(current_config.get('title_en', 'Data Trends'))

            def human_format_left(x, pos):
                if x == 0: return "0"
                if abs(x) < 1000: return f"{x:.2f}"
                return f"{x:,.0f}"
            
            ax.yaxis.set_major_formatter(mticker.FuncFormatter(human_format_left))
            ax.grid(True, linestyle=':', alpha=0.6)
            st.pyplot(fig)
    else:
        st.info("请选择变量。")

elif not fetch_btn:
    st.info(" 请先在左侧提取数据。")
