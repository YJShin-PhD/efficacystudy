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
                    result_df.to_excel(writer, index=False, sheet_name=f'Stat_{method}'[:30])
    return output.getvalue()

# 2. 로그인 세션 관리 (문법 오류 수정 지점)
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_id = None
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

# 3. 권한별 레이아웃 구성
user_role = USER_DB[st.session_state.user_id]["role"]

if user_role == "admin":
    tabs = st.tabs(["📊 Study Viewer", "⚙️ Admin Management"])
else:
    tabs = st.tabs(["📊 Study Viewer"])

# --- [Tab 1: 데이터 시각화 및 분석] ---
with tabs[0]:
    user_prefix = USER_DB[st.session_state.user_id].get("prefix", "")
    available_files = load_study_files(user_prefix)
    
    if not available_files:
        st.info("조회 가능한 실험 데이터가 없습니다. 관리자에게 문의하세요.")
    else:
        selected_file = st.selectbox("🔬 분석할 실험 선택", available_files)
        file_path = os.path.join(DATA_DIR, selected_file)
        df = pd.read_excel(file_path) if selected_file.endswith('.xlsx') else pd.read_csv(file_path)
        
        # --- 사이드바 설정 (오류 복구) ---
        st.sidebar.header("📊 분석 설정")
        cols = df.columns.tolist()
        group_col = st.sidebar.selectbox("그룹 열", cols, index=cols.index('Group') if 'Group' in cols else 0)
        day_col = st.sidebar.selectbox("날짜 열", cols, index=cols.index('Day') if 'Day' in cols else 0)
        
        # [해결] 'Group'이 데이터 열로 잡히지 않도록 기본값 조정 (보통 3번째 열이 첫 번째 수치 데이터)
        non_data_cols = [group_col, day_col]
        data_candidates = [c for c in cols if c not in non_data_cols]
        weight_col = st.sidebar.selectbox("데이터(수치) 열 선택", data_candidates, index=0)

        all_days = sorted(df[day_col].unique())
        # [복구] 날짜 슬라이더
        day_range = st.sidebar.slider("그래프 표시 범위(Day)", int(min(all_days)), int(max(all_days)), (int(min(all_days)), int(max(all_days))))
        
        all_groups = sorted(df[group_col].unique())
        selected_groups = st.sidebar.multiselect("분석 그룹 필터", all_groups, default=all_groups)
        
        # 통계 시점 및 대조군 설정
        target_day = st.sidebar.selectbox("통계 분석 기준일(Day)", all_days, index=len(all_days)-1)
        control_group = st.sidebar.selectbox("대조군(Control) 지정", all_groups, index=0)

        # --- 그래프 스타일 적용 ---
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
        fig.update_layout(title=f"Trend: {weight_col}", xaxis_title="Day", yaxis_title=weight_col, plot_bgcolor='white')
        st.plotly_chart(fig, use_container_width=True)

        # --- 통계 버튼 및 결과 복구 ---
        st.divider()
        st.subheader(f"🧬 통계 분석 결과 (Day {target_day})")
        analysis_df = df[(df[day_col] == target_day) & (df[group_col].isin(selected_groups))]
        summary_table = analysis_df.groupby([group_col])[weight_col].agg(['count', 'mean', 'sem']).reset_index()
        st.dataframe(summary_table.style.format(precision=2), use_container_width=True)

        col1, col2 = st.columns(2)
        if col1.button("🚀 Run Dunnett's Test"):
            try:
                others = [g for g in selected_groups if g != control_group]
                samples = [analysis_df[analysis_df[group_col] == g][weight_col] for g in others]
                ctrl = analysis_df[analysis_df[group_col] == control_group][weight_col]
                res = stats.dunnett(*samples, control=ctrl)
                st.session_state.stat_results['Dunnett'] = pd.DataFrame({"Comparison": [f"{control_group} vs {g}" for g in others], "p-value": res.pvalue})
                st.dataframe(st.session_state.stat_results['Dunnett'])
            except Exception as e: st.error(f"Error: {e}")

        if col2.button("🚀 Run Tukey HSD"):
            try:
                tukey = pairwise_tukeyhsd(analysis_df[weight_col], analysis_df[group_col])
                st.session_state.stat_results['Tukey'] = pd.DataFrame(data=tukey.summary().data[1:], columns=tukey.summary().data[0])
                st.dataframe(st.session_state.stat_results['Tukey'])
            except Exception as e: st.error(f"Error: {e}")

        # 다운로드 버튼
        excel_data = to_excel_final(summary_table, st.session_state.stat_results)
        st.sidebar.download_button("📥 통합 리포트 다운로드", data=excel_data, file_name=f"Report_{selected_file}.xlsx")

# --- [Tab 2: 관리자 관리 (Admin 전용)] ---
if user_role == "admin":
    with tabs[1]:
        st.header("📤 실험 데이터 등록")
        client_target = st.selectbox("업로드 대상 고객사", [k for k, v in USER_DB.items() if v['role'] == 'user'])
        up_file = st.file_uploader("엑셀/CSV 파일 선택", type=['xlsx', 'csv'])
        
        if st.button("서버에 저장"):
            if up_file:
                prefix = USER_DB[client_target]['prefix']
                save_path = os.path.join(DATA_DIR, f"{prefix}{up_file.name}")
                with open(save_path, "wb") as f:
                    f.write(up_file.getbuffer())
                st.success(f"저장 완료: {prefix}{up_file.name}")
                st.rerun()

        st.divider()
        st.subheader("🗑️ 파일 삭제 관리")
        all_f = load_study_files()
        for f in all_f:
            if st.button(f"삭제: {f}", key=f):
                os.remove(os.path.join(DATA_DIR, f))
                st.rerun()

st.sidebar.divider()
if st.sidebar.button("Log Out"):
    st.session_state.logged_in = False
    st.rerun()
