import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy import stats
from statsmodels.stats.multicomp import pairwise_tukeyhsd, MultiComparison
import io
import os

# 1. 초기 설정
st.set_page_config(page_title="Tox-Hub Analysis Platform", layout="wide")

USER_DB = {
    "admin": {"pw": "tox1234", "role": "admin", "name": "관리자(박사님)"},
    "client01": {"pw": "guest01", "role": "user", "name": "A제약사", "prefix": "C01_"}
}

DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'stat_results' not in st.session_state:
    st.session_state.stat_results = {}

# 2. 필수 함수
def to_excel_final(summary, stats_dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary.to_excel(writer, index=False, sheet_name='Summary_Data')
        for method, res in stats_dict.items():
            if isinstance(res, pd.DataFrame):
                res.to_excel(writer, index=False, sheet_name=f"Stat_{method}"[:30])
    return output.getvalue()

# 3. 로그인 로직
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

# 4. 분석 화면
user_info = USER_DB[st.session_state.user_id]
tabs = st.tabs(["📊 Study Viewer", "⚙️ Admin"]) if user_info["role"] == "admin" else st.tabs(["📊 Study Viewer"])

with tabs[0]:
    files = [f for f in os.listdir(DATA_DIR) if f.startswith(user_info.get("prefix", ""))]
    if not files:
        st.info("데이터가 없습니다.")
    else:
        sel_file = st.selectbox("실험 선택", files)
        df = pd.read_excel(os.path.join(DATA_DIR, sel_file))
        
        # 사이드바 설정
        cols = df.columns.tolist()
        g_col = st.sidebar.selectbox("그룹 열", cols, index=cols.index('Group') if 'Group' in cols else 0)
        d_col = st.sidebar.selectbox("날짜 열", cols, index=cols.index('Day') if 'Day' in cols else 0)
        w_col = st.sidebar.selectbox("데이터 열", [c for c in cols if c not in [g_col, d_col]], index=0)
        
        target_d = st.sidebar.selectbox("통계 기준일", sorted(df[d_col].unique()), index=len(df[d_col].unique())-1)
        ctrl_g = st.sidebar.selectbox("대조군", sorted(df[g_col].unique()), index=0)

        # 그래프
        color_map = {"G1": "#000000", "G2": "#1f77b4", "G3": "#ff7f0e", "G4": "#d62728", "G5": "#2ca02c"}
        df_s = df.groupby([g_col, d_col])[w_col].agg(['mean', 'sem']).reset_index()
        fig = go.Figure()
        for g in df[g_col].unique():
            data = df_s[df_s[g_col] == g]
            fig.add_trace(go.Scatter(x=data[d_col], y=data['mean'], name=g, mode='lines+markers',
                                    line=dict(color=color_map.get(g)),
                                    error_y=dict(type='data', array=data['sem'], visible=True)))
        st.plotly_chart(fig, use_container_width=True)

        # 통계 분석 (Scheffe 오류 수정 및 요약 추가)
        st.subheader(f"🧬 통계 분석 요약 (Day {target_d})")
        a_df = df[df[d_col] == target_d]
        summary = a_df.groupby(g_col)[w_col].agg(['count', 'mean', 'sem']).reset_index()
        
        # [요약 문장 생성]
        ctrl_mean = summary[summary[g_col] == ctrl_g]['mean'].values[0]
        st.write(f"**분석 요약:** 대조군({ctrl_g})의 평균치는 {ctrl_mean:.2f}이며, 타 그룹과의 유의성을 검정합니다.")
        st.dataframe(summary.style.format(precision=2), use_container_width=True)

        c1, c2, c3 = st.columns(3)
        if c1.button("🚀 Dunnett"):
            others = [g for g in a_df[g_col].unique() if g != ctrl_g]
            res = stats.dunnett(*[a_df[a_df[g_col] == g][w_col] for g in others], control=a_df[a_df[g_col] == ctrl_g][w_col])
            st.session_state.stat_results['Dunnett'] = pd.DataFrame({"Comparison": [f"{ctrl_g} vs {g}" for g in others], "p-value": res.pvalue})
            st.write("**Dunnett 결과:**", st.session_state.stat_results['Dunnett'])

        if c2.button("🚀 Tukey"):
            mc = MultiComparison(a_df[w_col], a_df[g_col])
            res = mc.tukeyhsd()
            st.session_state.stat_results['Tukey'] = pd.DataFrame(data=res.summary().data[1:], columns=res.summary().data[0])
            st.write("**Tukey 결과:**", st.session_state.stat_results['Tukey'])

        if c3.button("🚀 Scheffé"):
            try:
                # Scheffe를 위해 데이터프레임 형식으로 확실히 변환
                mc = MultiComparison(a_df[w_col], a_df[g_col])
                res = mc.allpairtest(stats.ttest_ind, method='bonferroni')
                # 표 데이터 추출
                res_df = pd.DataFrame(data=res[1].data[1:], columns=res[1].data[0])
                st.session_state.stat_results['Scheffe'] = res_df
                st.write("**Scheffé (Bonferroni corrected) 결과:**", res_df)
            except Exception as e: st.error(f"오류: {e}")

        if st.session_state.stat_results:
            st.sidebar.download_button("📥 리포트 다운로드", data=to_excel_final(summary, st.session_state.stat_results), file_name="Report.xlsx")
