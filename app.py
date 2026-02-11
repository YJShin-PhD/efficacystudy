import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy import stats
from statsmodels.stats.multicomp import pairwise_tukeyhsd, MultiComparison
import io
import os

# 1. 페이지 설정 및 사용자 DB
st.set_page_config(page_title="Tox-Hub Analysis Platform", layout="wide")

USER_DB = {
    "admin": {"pw": "tox1234", "role": "admin", "name": "관리자(박사님)"},
    "client01": {"pw": "guest01", "role": "user", "name": "A제약사", "prefix": "C01_"}
}

DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# 함수 정의
def load_study_files(prefix=""):
    if not os.path.exists(DATA_DIR): return []
    files = [f for f in os.listdir(DATA_DIR) if f.endswith(('.xlsx', '.csv'))]
    if prefix:
        return sorted([f for f in files if f.startswith(prefix)])
    return sorted(files)

def to_excel_final(summary, stats_dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary.to_excel(writer, index=False, sheet_name='Summary_Data')
        if stats_dict:
            for method, result_df in stats_dict.items():
                if result_df is not None:
                    # 시트 이름 제한(31자) 준수
                    safe_name = f'Stat_{method}'[:30]
                    result_df.to_excel(writer, index=False, sheet_name=safe_name)
    return output.getvalue()

# 2. 로그인 세션 관리 (SyntaxError 해결)
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'stat_results' not in st.session_state:
    st.session_state.stat_results = {}

if not st.session_state.logged_in:
    st.title("🔐 Toxicology Data Portal")
    with st.form("login_form"):
        i_id = st.text_input("아이디(ID)")
        i_pw = st.text_input("비밀번호(Password)", type="password")
        if st.form_submit_button("로그인"):
            if i_id in USER_DB and USER_DB[i_id]["pw"] == i_pw:
                st.session_state.logged_in = True
                st.session_state.user_id = i_id
                st.rerun()
            else:
                st.error("정보가 일치하지 않습니다.")
    st.stop()

# 3. 권한 설정
user_info = USER_DB[st.session_state.user_id]
user_role = user_info["role"]

if user_role == "admin":
    tabs = st.tabs(["📊 Study Viewer", "⚙️ Admin Management"])
else:
    tabs = st.tabs(["📊 Study Viewer"])

# --- [Tab 1: 데이터 시각화 및 분석] ---
with tabs[0]:
    user_prefix = user_info.get("prefix", "")
    available_files = load_study_files(user_prefix)
    
    if not available_files:
        st.info("조회 가능한 실험 데이터가 없습니다.")
    else:
        selected_file = st.selectbox("🔬 분석할 실험 선택", available_files)
        file_path = os.path.join(DATA_DIR, selected_file)
        df = pd.read_excel(file_path) if selected_file.endswith('.xlsx') else pd.read_csv(file_path)
        
        # --- 사이드바 설정 (데이터 열 자동 지정 오류 해결) ---
        st.sidebar.header("📊 분석 설정")
        cols = df.columns.tolist()
        group_col = st.sidebar.selectbox("그룹 열", cols, index=cols.index('Group') if 'Group' in cols else 0)
        day_col = st.sidebar.selectbox("날짜 열", cols, index=cols.index('Day') if 'Day' in cols else 0)
        
        # 수치 데이터만 후보로 추출하여 'Group'이 선택되는 것 방지
        data_candidates = [c for c in cols if c not in [group_col, day_col]]
        weight_col = st.sidebar.selectbox("데이터(수치) 열 선택", data_candidates, index=0)

        all_days = sorted(df[day_col].unique())
        day_range = st.sidebar.slider("그래프 표시 범위(Day)", int(min(all_days)), int(max(all_days)), (int(min(all_days)), int(max(all_days))))
        
        all_groups = sorted(df[group_col].unique())
        selected_groups = st.sidebar.multiselect("분석 그룹 필터", all_groups, default=all_groups)
        
        target_day = st.sidebar.selectbox("통계 분석 기준일(Day)", all_days, index=len(all_days)-1)
        control_group = st.sidebar.selectbox("대조군(Control) 지정", all_groups, index=0)

        # --- 그래프 출력 (색상 복구) ---
        color_map = {"G1": "#000000", "G2": "#1f77b4", "G3": "#ff7f0e", "G4": "#d62728", "G5": "#2ca02c"}
        
        graph_df = df[(df[group_col].isin(selected_groups)) & (df[day_col] >= day_range[0]) & (df[day_col] <= day_range[1])]
        df_stats = graph_df.groupby([group_col, day_col])[weight_col].agg(['mean', 'sem']).reset_index()
        
        fig = go.Figure()
        for group in selected_groups:
            g_data = df_stats[df_stats[group_col] == group]
            fig.add_trace(go.Scatter(
                x=g_data[day_col], y=g_data['mean'], name=group,
                mode='lines+markers',
                line=dict(color=color_map.get(group, None), width=3),
                error_y=dict(type='data', array=g_data['sem'], visible=True)
            ))
        fig.update_layout(xaxis_title="Day", yaxis_title=weight_col, plot_bgcolor='white')
        st.plotly_chart(fig, use_container_width=True)

        # --- 통계 분석 섹션 (Scheffe 추가) ---
        st.divider()
        st.subheader(f"🧬 통계 분석 결과 (Day {target_day
