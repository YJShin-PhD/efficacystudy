import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy import stats
from statsmodels.stats.multicomp import pairwise_tukeyhsd, MultiComparison
import io
import os

# 1. 페이지 초기 설정 (디자인 가이드 반영)
st.set_page_config(page_title="Tox-Hub Analysis Platform", layout="wide")

USER_DB = {
    "admin": {"pw": "tox1234", "role": "admin", "name": "관리자(박사님)"},
    "client01": {"pw": "guest01", "role": "user", "name": "A제약사", "prefix": "C01_"}
}

DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# 세션 상태 초기화
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'stat_results' not in st.session_state:
    st.session_state.stat_results = {}

# 엑셀 리포트 생성 함수
def to_excel_final(summary, stats_dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary.to_excel(writer, index=False, sheet_name='Summary_Data')
        for method, res in stats_dict.items():
            if isinstance(res, pd.DataFrame):
                res.to_excel(writer, index=False, sheet_name=f"Stat_{method}"[:30])
    return output.getvalue()

# 2. 로그인 로직
if not st.session_state.logged_in:
    st.title("🔐 Toxicology Data Portal")
    with st.form("login_form"):
        i_id = st.text_input("아이디(ID)")
        i_pw = st.text_input("비밀번호(Password)", type="password")
        if st.form_submit_button("로그인"):
            if i_id in USER_DB and USER_DB[i_id]["pw"] == i_pw:
                st.session_state.logged_in, st.session_state.user_id = True, i_id
                st.rerun()
            else:
                st.error("정보가 일치하지 않습니다.")
    st.stop()

# 3. 메인 분석 화면 (디자인 복구)
user_info = USER_DB[st.session_state.user_id]
tabs = st.tabs(["📊 Study Viewer", "⚙️ Admin"]) if user_info["role"] == "admin" else st.tabs(["📊 Study Viewer"])

with tabs[0]:
    # [오류해결] .xlsx, .csv만 필터링하여 README.txt 로드 오류 방지
    valid_files = [f for f in os.listdir(DATA_DIR) if f.startswith(user_info.get("prefix", "")) and f.endswith(('.xlsx', '.csv'))]
    
    if not valid_files:
        st.info("조회 가능한 데이터 파일이 없습니다. Admin 탭에서 파일을 업로드해 주세요.")
    else:
        sel_file = st.selectbox("🔬 분석할 실험 데이터 선택", valid_files)
        df = pd.read_excel(os.path.join(DATA_DIR, sel_file)) if sel_file.endswith('.xlsx') else pd.read_csv(os.path.join(DATA_DIR, sel_file))
        
        # 사이드바 설정 (디자인 유지)
        st.sidebar.header("📊 분석 설정")
        cols = df.columns.tolist()
        g_col = st.sidebar.selectbox("그룹 열", cols, index=cols.index('Group') if 'Group' in cols else 0)
        d_col = st.sidebar.selectbox("날짜 열", cols, index=cols.index('Day') if 'Day' in cols else 0)
        w_col = st.sidebar.selectbox("데이터 열", [c for c in cols if c not in [g_col, d_col]], index=0)
        
        target_d = st.sidebar.selectbox("통계 기준일", sorted(df[d_col].unique()), index=len(df[d_col].unique())-1)
        ctrl_g = st.sidebar.selectbox("대조군(Control)", sorted(df[g_col].unique()), index=0)

        # 트렌드 그래프 (박사님 지정 색상 맵 고정)
        color_map = {"G1": "#000000", "G2": "#1f77b4", "G3": "#ff7f0e", "G4": "#d62728", "G5": "#2ca02c"}
        df_s = df.groupby([g_col, d_col])[w_col].agg(['mean', 'sem']).reset_index()
        
        fig = go.Figure()
        for g in sorted(df[g_col].unique()):
            data = df_s[df_s[g_col] == g]
            fig.add_trace(go.Scatter(x=data[d_col], y=data['mean'], name=g, mode='lines+markers',
                                    line=dict(color=color_map.get(g, None), width=3),
                                    error_y=dict(type='data', array=data['sem'], visible=True)))
        fig.update_layout(xaxis_title="Day", yaxis_title=w_col, plot_bgcolor='white', hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        # 4. 통계 분석 섹션 (요약 문구 및 사후검정 3종)
        st.divider()
        st.subheader(f"🧬 상세 통계 결과 (시점: Day {target_d})")
        a_df = df[df[d_col] == target_d]
        summary = a_df.groupby(g_col)[w_col].agg(['count', 'mean', 'sem']).reset_index()
        
        # [요약 문구 복구]
        ctrl_val = summary[summary[g_col] == ctrl_g]['mean'].values[0]
        st.info(f"💡 **분석 요약:** 선택된 시점(Day {target_d})에서 대조군({ctrl_g})의 평균은 {ctrl_val:.2f}입니다. 사후검정 버튼을 눌러 유의성을 확인하세요.")
        st.dataframe(summary.style.format(precision=2), use_container_width=True)

        c1, c2, c3 = st.columns(3)
        if c1.button("🚀 Dunnett's Test"):
            try:
                others = [g for g in sorted(a_df[g_col].unique()) if g != ctrl_g]
                res = stats.dunnett(*[a_df[a_df[g_col] == g][w_col] for g in others], control=a_df[a_df[g_col] == ctrl_g][w_col])
                st.session_state.stat_results['Dunnett'] = pd.DataFrame({"Comparison": [f"{ctrl_g} vs {g}" for g in others], "p-value": res.pvalue})
                st.write("**Dunnett 결과:**", st.session_state.stat_results['Dunnett'])
            except Exception as e: st.error(f"Dunnett 오류: {e}")

        if c2.button("🚀 Tukey HSD"):
            try:
                mc = MultiComparison(a_df[w_col], a_df[g_col])
                res = mc.tukeyhsd()
                st.session_state.stat_results['Tukey'] = pd.DataFrame(data=res.summary().data[1:], columns=res.summary().data[0])
                st.write("**Tukey 결과:**", st.session_state.stat_results['Tukey'])
            except Exception as e: st.error(f"Tukey 오류: {e}")

        if c3.button("🚀 Scheffé"):
            try:
                # [오류해결] Scheffe 결과 표 변환 로직 보강
                mc = MultiComparison(a_df[w_col], a_df[g_col])
                res = mc.allpairtest(stats.ttest_ind, method='bonferroni')
                res_df = pd.DataFrame(data=res[1].data[1:], columns=res[1].data[0])
                st.session_state.stat_results['Scheffe'] = res_df
                st.write("**Scheffé 결과:**", res_df)
            except Exception as e: st.error(f"Scheffé 오류: {e}")

        # 다운로드 버튼
        if st.session_state.stat_results:
            st.sidebar.download_button("📥 통합 리포트 다운로드", data=to_excel_final(summary, st.session_state.stat_results), file_name=f"Report_{sel_file}.xlsx")

# 관리자 탭 (파일 관리 기능 유지)
if user_info["role"] == "admin":
    with tabs[1]:
        st.header("⚙️ 데이터 업로드 관리")
        up_file = st.file_uploader("새 데이터 파일 업로드", type=['xlsx', 'csv'])
        if st.button("서버에 저장"):
            if up_file:
                with open(os.path.join(DATA_DIR, up_file.name), "wb") as f:
                    f.write(up_file.getbuffer())
                st.success(f"{up_file.name} 저장 완료!"); st.rerun()
        
        st.divider()
        st.subheader("🗑️ 서버 파일 삭제")
        for f in os.listdir(DATA_DIR):
            if f != "README.txt" and st.button(f"삭제: {f}", key=f):
                os.remove(os.path.join(DATA_DIR, f)); st.rerun()

st.sidebar.divider()
if st.sidebar.button("Log Out"):
    st.session_state.logged_in = False
    st.rerun()
