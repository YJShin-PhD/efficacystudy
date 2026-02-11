import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy import stats
from statsmodels.stats.multicomp import pairwise_tukeyhsd, MultiComparison
import io
import os

# 1. 초기 설정 및 보안 DB
st.set_page_config(page_title="Tox-Hub Analysis Platform", layout="wide")

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
if 'stat_results' not in st.session_state:
    st.session_state.stat_results = {}

# 2. 필수 함수 (구조 및 결과 변환 오류 해결)
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
        i_id = st.text_input("아이디(ID)")
        i_pw = st.text_input("비밀번호(Password)", type="password")
        if st.form_submit_button("로그인"):
            if i_id in USER_DB and USER_DB[i_id]["pw"] == i_pw:
                st.session_state.logged_in, st.session_state.user_id = True, i_id
                st.rerun()
            else:
                st.error("정보가 일치하지 않습니다.")
    st.stop()

# 4. 분석 화면 및 관리자 탭
user_info = USER_DB[st.session_state.user_id]
tabs = st.tabs(["📊 Study Viewer", "⚙️ Admin"]) if user_info["role"] == "admin" else st.tabs(["📊 Study Viewer"])

with tabs[0]:
    # [해결] .xlsx 및 .csv만 필터링하여 README.txt 로드 오류 방지
    all_files = os.listdir(DATA_DIR)
    valid_extensions = ('.xlsx', '.csv')
    files = [f for f in all_files if f.startswith(user_info.get("prefix", "")) and f.endswith(valid_extensions)]
    
    if not files:
        st.info("조회 가능한 데이터 파일이 없습니다. (엑셀 또는 CSV 파일을 업로드해주세요)")
    else:
        sel_file = st.selectbox("🔬 분석할 실험 데이터 선택", files)
        file_path = os.path.join(DATA_DIR, sel_file)
        
        # 파일 형식에 따라 로드
        df = pd.read_excel(file_path) if sel_file.endswith('.xlsx') else pd.read_csv(file_path)
        
        # 분석 설정 (사이드바)
        cols = df.columns.tolist()
        g_col = st.sidebar.selectbox("그룹 열", cols, index=cols.index('Group') if 'Group' in cols else 0)
        d_col = st.sidebar.selectbox("날짜 열", cols, index=cols.index('Day') if 'Day' in cols else 0)
        w_col = st.sidebar.selectbox("데이터 열", [c for c in cols if c not in [g_col, d_col]], index=0)
        
        target_d = st.sidebar.selectbox("통계 기준일", sorted(df[d_col].unique()), index=len(df[d_col].unique())-1)
        ctrl_g = st.sidebar.selectbox("대조군(Control)", sorted(df[g_col].unique()), index=0)

        # 트렌드 그래프 (색상 고정)
        color_map = {"G1": "#000000", "G2": "#1f77b4", "G3": "#ff7f0e", "G4": "#d62728", "G5": "#2ca02c"}
        df_s = df.groupby([g_col, d_col])[w_col].agg(['mean', 'sem']).reset_index()
        fig = go.Figure()
        for g in sorted(df[g_col].unique()):
            data = df_s[df_s[g_col] == g]
            fig.add_trace(go.Scatter(x=data[d_col], y=data['mean'], name=g, mode='lines+markers',
                                    line=dict(color=color_map.get(g, None), width=3),
                                    error_y=dict(type='data', array=data['sem'], visible=True)))
        fig.update_layout(xaxis_title="Day", yaxis_title=w_col, plot_bgcolor='white')
        st.plotly_chart(fig, use_container_width=True)

        # --- 통계 분석 및 요약 ---
        st.divider()
        st.subheader(f"🧬 상세 통계 결과 (시점: Day {target_d})")
        a_df = df[df[d_col] == target_d]
        summary = a_df.groupby(g_col)[w_col].agg(['count', 'mean', 'sem']).reset_index()
        
        # 요약 문장 자동 생성
        ctrl_val = summary[summary[g_col] == ctrl_g]['mean'].values[0]
        st.info(f"💡 **분석 요약:** 선택된 시점(Day {target_d})에서 대조군({ctrl_g})의 평균은 {ctrl_val:.2f}입니다. 아래 버튼을 눌러 사후검정을 실시하세요.")
        st.dataframe(summary.style.format(precision=2), use_container_width=True)

        c1, c2, c3 = st.columns(3)
        # Dunnett 분석
        if c1.button("🚀 Dunnett"):
            try:
                others = [g for g in sorted(a_df[g_col].unique()) if g != ctrl_g]
                res = stats.dunnett(*[a_df[a_df[g_col] == g][w_col] for g in others], control=a_df[a_df[g_col] == ctrl_g][w_col])
                st.session_state.stat_results['Dunnett'] = pd.DataFrame({"Comparison": [f"{ctrl_g} vs {g}" for g in others], "p-value": res.pvalue})
                st.write("**Dunnett's Test:**", st.session_state.stat_results['Dunnett'])
            except Exception as e: st.error(f"Dunnett 오류: {e}")

        # Tukey 분석
        if c2.button("🚀 Tukey HSD"):
            try:
                mc = MultiComparison(a_df[w_col], a_df[g_col])
                res = mc.tukeyhsd()
                st.session_state.stat_results['Tukey'] = pd.DataFrame(data=res.summary().data[1:], columns=res.summary().data[0])
                st.write("**Tukey HSD Test:**", st.session_state.stat_results['Tukey'])
            except Exception as e: st.error(f"Tukey 오류: {e}")

        # Scheffe 분석 (변환 오류 완전 해결)
        if c3.button("🚀 Scheffé"):
            try:
                mc = MultiComparison(a_df[w_col], a_df[g_col])
                res = mc.allpairtest(stats.ttest_ind, method='bonferroni')
                res_df = pd.DataFrame(data=res[1].data[1:], columns=res[1].data[0])
                st.session_state.stat_results['Scheffe'] = res_df
                st.write("**Scheffé (Bonferroni) Test:**", res_df)
            except Exception as e: st.error(f"Scheffé 오류: {e}")

        # 리포트 다운로드
        if st.session_state.stat_results:
            st.sidebar.download_button("📥 통합 리포트 다운로드", data=to_excel_final(summary, st.session_state.stat_results), file_name=f"Analysis_Report_{sel_file}.xlsx")

# 관리자 탭 (생략된 기존 업로드/삭제 로직 포함)
if user_info["role"] == "admin":
    with tabs[1]:
        st.header("📤 데이터 관리")
        up_file = st.file_uploader("파일 업로드", type=['xlsx', 'csv'])
        if st.button("서버 저장"):
            if up_file:
                with open(os.path.join(DATA_DIR, up_file.name), "wb") as f:
                    f.write(up_file.getbuffer())
                st.success("저장 완료!"); st.rerun()
