import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy import stats
from statsmodels.stats.multicomp import pairwise_tukeyhsd, MultiComparison
import io
import os

# 1. 페이지 설정 및 사용자 DB
st.set_page_config(page_title="Tox-Hub Platform", layout="wide")

USER_DB = {
    "admin": {"pw": "tox1234", "role": "admin", "name": "관리자(박사님)"},
    "client01": {"pw": "guest01", "role": "user", "name": "A제약사", "prefix": "C01_"}
}

DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# 함수 정의
def load_study_files(prefix=""):
    files = [f for f in os.listdir(DATA_DIR) if f.endswith(('.xlsx', '.csv'))]
    if prefix:
        return sorted([f for f in files if f.startswith(prefix)])
    return sorted(files)

def to_excel_final(summary, stats_dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary.to_excel(writer, index=False, sheet_name='Summary_Data')
        for method, result_df in stats_dict.items():
            if result_df is not None:
                result_df.to_excel(writer, index=False, sheet_name=f'Stat_{method}'[:30])
    return output.getvalue()

# 로그인 세션
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.stat_results = {}

if not st.session_state.logged_in:
    st.title("🔐 Toxicology Data Portal")
    with st.form("login"):
        i_id = st.text_input("ID")
        i_pw = st.text_input("PW", type="password")
        if st.form_submit_button("로그인"):
            if i_id in USER_DB and USER_DB[i_id]["pw"] == i_pw:
                st.session_state.logged_in, st.session_state.user_id = True, i_id
                st.rerun()
    st.stop()

# 메인 레이아웃
if st.session_state.user_role := USER_DB[st.session_state.user_id]["role"] == "admin":
    tabs = st.tabs(["📊 Study Viewer", "⚙️ Admin Management"])
else:
    tabs = st.tabs(["📊 Study Viewer"])

with tabs[0]:
    user_prefix = USER_DB[st.session_state.user_id].get("prefix", "")
    available_files = load_study_files(user_prefix)
    
    if not available_files:
        st.info("조회 가능한 데이터가 없습니다.")
    else:
        selected_file = st.selectbox("🔬 실험 선택", available_files)
        df = pd.read_excel(os.path.join(DATA_DIR, selected_file))
        
        # --- [복구된 사이드바 설정] ---
        st.sidebar.header("📊 분석 설정")
        cols = df.columns.tolist()
        group_col = st.sidebar.selectbox("그룹 열", cols, index=cols.index('Group') if 'Group' in cols else 0)
        day_col = st.sidebar.selectbox("날짜 열", cols, index=cols.index('Day') if 'Day' in cols else 0)
        
        # [오류 해결] 데이터 열이 Group으로 잡히지 않도록 인덱스 조정 (보통 2번째 이후 열이 데이터)
        default_data_idx = 2 if len(cols) > 2 else 0
        weight_col = st.sidebar.selectbox("데이터(체중) 열", cols, index=default_data_idx)

        all_days = sorted(df[day_col].unique())
        # [복구] 날짜 범위 슬라이더
        day_range = st.sidebar.slider("분석 날짜 범위", int(min(all_days)), int(max(all_days)), (int(min(all_days)), int(max(all_days))))
        
        all_groups = sorted(df[group_col].unique())
        selected_groups = st.sidebar.multiselect("그룹 필터", all_groups, default=all_groups)
        
        # 통계 시점 선택
        target_day = st.sidebar.selectbox("통계 분석 시점(Day)", all_days, index=len(all_days)-1)
        control_group = st.sidebar.selectbox("대조군(Control)", all_groups, index=0)

        # --- [복구된 시각화] ---
        # 색상/스타일 맵
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

        # --- [복구된 ANOVA 버튼 섹션] ---
        st.subheader(f"🧬 상세 통계 분석 (시점: Day {target_day})")
        analysis_df = df[(df[day_col] == target_day) & (df[group_col].isin(selected_groups))]
        summary = analysis_df.groupby([group_col])[weight_col].agg(['count', 'mean', 'sem']).reset_index()
        st.dataframe(summary.style.format(precision=2), use_container_width=True)

        c1, c2 = st.columns(2)
        if c1.button("🚀 Dunnett's Test"):
            try:
                others = [g for g in selected_groups if g != control_group]
                samples = [analysis_df[analysis_df[group_col] == g][weight_col] for g in others]
                ctrl = analysis_df[analysis_df[group_col] == control_group][weight_col]
                res = stats.dunnett(*samples, control=ctrl)
                st.session_state.stat_results['Dunnett'] = pd.DataFrame({"Comparison": [f"{control_group} vs {g}" for g in others], "p-value": res.pvalue})
                st.dataframe(st.session_state.stat_results['Dunnett'])
            except Exception as e: st.error(f"오류: {e}")

        if c2.button("🚀 Tukey HSD"):
            try:
                tukey = pairwise_tukeyhsd(analysis_df[weight_col], analysis_df[group_col])
                st.session_state.stat_results['Tukey'] = pd.DataFrame(data=tukey.summary().data[1:], columns=tukey.summary().data[0])
                st.dataframe(st.session_state.stat_results['Tukey'])
            except Exception as e: st.error(f"오류: {e}")

        # 리포트 다운로드
        excel_data = to_excel_final(summary, st.session_state.stat_results)
        st.sidebar.download_button("📥 리포트 다운로드", data=excel_data, file_name=f"Report_{selected_file}.xlsx")

# 관리자 탭 (기존 코드 유지)
if USER_DB[st.session_state.user_id]["role"] == "admin":
    with tabs[1]:
        st.header("📤 관리자 업로드")
        # ... (파일 저장 로직)
