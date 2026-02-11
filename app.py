import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy import stats
from statsmodels.stats.multicomp import pairwise_tukeyhsd, MultiComparison
import io
import os

# 1. 페이지 설정 및 초기화
st.set_page_config(page_title="Tox-Hub Analysis Platform", layout="wide")

# 사용자 DB 설정
USER_DB = {
    "admin": {"pw": "tox1234", "role": "admin", "name": "관리자(박사님)"},
    "client01": {"pw": "guest01", "role": "user", "name": "A제약사", "prefix": "C01_"}
}

DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# 세션 상태 초기화 (AttributeError 방지)
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
if 'stat_results' not in st.session_state:
    st.session_state.stat_results = {}

# 2. 필수 함수 정의
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
        for method, result_df in stats_dict.items():
            if result_df is not None:
                # 시트명 제한(31자) 준수 및 오류 방지
                safe_name = f"Stat_{method}"[:30]
                result_df.to_excel(writer, index=False, sheet_name=safe_name)
    return output.getvalue()

# 3. 로그인 로직
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

# 4. 메인 화면 구성
user_info = USER_DB[st.session_state.user_id]
user_role = user_info["role"]

if user_role == "admin":
    tabs = st.tabs(["📊 Study Viewer", "⚙️ Admin Management"])
else:
    tabs = st.tabs(["📊 Study Viewer"])

# --- [Tab 1: 분석 및 시각화] ---
with tabs[0]:
    user_prefix = user_info.get("prefix", "")
    available_files = load_study_files(user_prefix)
    
    if not available_files:
        st.info("조회 가능한 실험 데이터가 없습니다.")
    else:
        selected_file = st.selectbox("🔬 실험 선택", available_files)
        file_path = os.path.join(DATA_DIR, selected_file)
        
        # 파일 형식에 따른 로드
        if selected_file.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)
            
        # 사이드바 설정 (데이터 열 오지정 복구)
        st.sidebar.header("📊 분석 설정")
        cols = df.columns.tolist()
        group_col = st.sidebar.selectbox("그룹 열", cols, index=cols.index('Group') if 'Group' in cols else 0)
        day_col = st.sidebar.selectbox("날짜 열", cols, index=cols.index('Day') if 'Day' in cols else 0)
        
        # 데이터 열에서 Group, Day 제외하여 자동 선택
        data_candidates = [c for c in cols if c not in [group_col, day_col]]
        weight_col = st.sidebar.selectbox("데이터(수치) 열", data_candidates, index=0)

        all_days = sorted(df[day_col].unique())
        day_range = st.sidebar.slider("날짜 범위", int(min(all_days)), int(max(all_days)), (int(min(all_days)), int(max(all_days))))
        
        all_groups = sorted(df[group_col].unique())
        selected_groups = st.sidebar.multiselect("그룹 필터", all_groups, default=all_groups)
        
        target_day = st.sidebar.selectbox("통계 기준일(Day)", all_days, index=len(all_days)-1)
        control_group = st.sidebar.selectbox("대조군(Control)", all_groups, index=0)

        # 그래프 출력
        color_map = {"G1": "#000000", "G2": "#1f77b4", "G3": "#ff7f0e", "G4": "#d62728", "G5": "#2ca02c"}
        graph_df = df[(df[group_col].isin(selected_groups)) & (df[day_col] >= day_range[0]) & (df[day_col] <= day_range[1])]
        df_stats = graph_df.groupby([group_col, day_col])[weight_col].agg(['mean', 'sem']).reset_index()
        
        fig = go.Figure()
        for group in selected_groups:
            g_data = df_stats[df_stats[group_col] == group]
            fig.add_trace(go.Scatter(
                x=g_data[day_col], y=g_data['mean'], name=group, mode='lines+markers',
                line=dict(color=color_map.get(group, None), width=3),
                error_y=dict(type='data', array=g_data['sem'], visible=True)
            ))
        fig.update_layout(xaxis_title="Day", yaxis_title=weight_col, plot_bgcolor='white')
        st.plotly_chart(fig, use_container_width=True)

        # 통계 섹션 (Scheffe 추가 및 f-string 오류 수정)
        st.divider()
        st.subheader(f"🧬 통계 분석 결과 (Day {target_day})") # 중괄호 닫기 확인
        
        analysis_df = df[(df[day_col] == target_day) & (df[group_col].isin(selected_groups))]
        summary = analysis_df.groupby([group_col])[weight_col].agg(['count', 'mean', 'sem']).reset_index()
        st.dataframe(summary.style.format(precision=2), use_container_width=True)

        c1, c2, c3 = st.columns(3)
        if c1.button("🚀 Dunnett"):
            try:
                others = [g for g in selected_groups if g != control_group]
                samples = [analysis_df[analysis_df[group_col] == g][weight_col] for g in others]
                ctrl = analysis_df[analysis_df[group_col] == control_group][weight_col]
                res = stats.dunnett(*samples, control=ctrl)
                st.session_state.stat_results['Dunnett'] = pd.DataFrame({"Comparison": [f"{control_group} vs {g}" for g in others], "p-value": res.pvalue})
                st.dataframe(st.session_state.stat_results['Dunnett'])
            except Exception as e: st.error(f"Error: {e}")

        if c2.button("🚀 Tukey HSD"):
            try:
                mc = MultiComparison(analysis_df[weight_col], analysis_df[group_col])
                result = mc.tukeyhsd()
                st.session_state.stat_results['Tukey'] = pd.DataFrame(data=result.summary().data[1:], columns=result.summary().data[0])
                st.dataframe(st.session_state.stat_results['Tukey'])
            except Exception as e: st.error(f"Error: {e}")

        if c3.button("🚀 Scheffé"):
            try:
                mc = MultiComparison(analysis_df[weight_col], analysis_df[group_col])
                res = mc.allpairtest(stats.ttest_ind, method='bonferroni')
                st.session_state.stat_results['Scheffe'] = res[1]
                st.dataframe(st.session_state.stat_results['Scheffe'])
            except Exception as e: st.error(f"Error: {e}")

        # 다운로드 (AttributeError 방지)
        if st.session_state.stat_results or not summary.empty:
            excel_data = to_excel_final(summary, st.session_state.stat_results)
            st.sidebar.download_button("📥 통합 리포트 다운로드", data=excel_data, file_name=f"Report_{selected_file}.xlsx")

# --- [Tab 2: 관리자] ---
if user_role == "admin":
    with tabs[1]:
        st.header("📤 파일 업로드 관리")
        client_sel = st.selectbox("대상 고객사", [k for k, v in USER_DB.items() if v['role'] == 'user'])
        up_file = st.file_uploader("파일 선택", type=['xlsx', 'csv'])
        if st.button("서버 저장"):
            if up_file:
                prefix = USER_DB[client_sel]['prefix']
                with open(os.path.join(DATA_DIR, f"{prefix}{up_file.name}"), "wb") as f:
                    f.write(up_file.getbuffer())
                st.success("저장되었습니다."); st.rerun()
        
        st.divider()
        all_f = load_study_files()
        for f in all_f:
            if st.button(f"삭제: {f}", key=f):
                os.remove(os.path.join(DATA_DIR, f)); st.rerun()

st.sidebar.divider()
if st.sidebar.button("Log Out"):
    st.session_state.logged_in = False
    st.rerun()
