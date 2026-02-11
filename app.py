import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy import stats
from statsmodels.stats.multicomp import pairwise_tukeyhsd, MultiComparison
import io
import os
import itertools

# 1. 페이지 설정 및 세션 초기화
st.set_page_config(page_title="Tox-Hub Analysis Platform", layout="wide")

USER_DB = {
    "admin": {"pw": "tox1234", "role": "admin", "name": "관리자(박사님)"},
    "client01": {"pw": "guest01", "role": "user", "name": "A제약사", "prefix": "C01_"}
}

DATA_DIR = "data"
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)

if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'stat_results' not in st.session_state: st.session_state.stat_results = {}
if 'summary_text' not in st.session_state: st.session_state.summary_text = "사후검정 버튼을 클릭하면 결과 요약이 여기에 표시됩니다."

# 엑셀 다운로드 함수
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
    with st.form("login"):
        i_id = st.text_input("아이디(ID)")
        i_pw = st.text_input("비밀번호(Password)", type="password")
        if st.form_submit_button("로그인"):
            if i_id in USER_DB and USER_DB[i_id]["pw"] == i_pw:
                st.session_state.logged_in, st.session_state.user_id = True, i_id
                st.rerun()
            else: st.error("정보가 일치하지 않습니다.")
    st.stop()

# 3. 메인 대시보드
user_info = USER_DB[st.session_state.user_id]
tabs = st.tabs(["📊 Study Viewer", "⚙️ Admin"]) if user_info["role"] == "admin" else st.tabs(["📊 Study Viewer"])

with tabs[0]:
    valid_files = [f for f in os.listdir(DATA_DIR) if f.startswith(user_info.get("prefix", "")) and f.endswith(('.xlsx', '.csv'))]
    
    if not valid_files:
        st.info("조회 가능한 데이터 파일이 없습니다.")
    else:
        sel_file = st.selectbox("🔬 분석 실험 데이터 선택", valid_files)
        df = pd.read_excel(os.path.join(DATA_DIR, sel_file)) if sel_file.endswith('.xlsx') else pd.read_csv(os.path.join(DATA_DIR, sel_file))
        
        # --- 사이드바 설정 ---
        st.sidebar.header("📊 분석 설정")
        cols = df.columns.tolist()
        
        # [개선] 데이터 열 초기값 스마트 선택 (No. 제외)
        g_col = st.sidebar.selectbox("그룹 열", cols, index=cols.index('Group') if 'Group' in cols else 0)
        d_col = st.sidebar.selectbox("날짜 열", cols, index=cols.index('Day') if 'Day' in cols else 0)
        
        # 분석 대상 후보: 숫자형이면서 No, Day가 아닌 열 우선 탐색
        candidate_cols = [c for c in cols if c not in [g_col, d_col, 'No.', 'no', 'No']]
        default_w_idx = 0
        for i, c in enumerate(candidate_cols):
            if any(kw in c.lower() for kw in ['weight', 'value', 'data', 'result']):
                default_w_idx = i
                break
        w_col = st.sidebar.selectbox("데이터 열", candidate_cols, index=default_w_idx)

        all_days = sorted(df[d_col].unique())
        day_range = st.sidebar.slider("표시 기간(Day)", int(min(all_days)), int(max(all_days)), (int(min(all_days)), int(max(all_days))))
        
        stat_options = ["전체 기간(All Days)"] + [str(d) for d in all_days]
        target_sel = st.sidebar.selectbox("통계 기준일", stat_options, index=len(stat_options)-1)
        ctrl_g = st.sidebar.selectbox("대조군(Control)", sorted(df[g_col].unique()), index=0)

        # --- 트렌드 그래프 (x축 실제 측정일 반영) ---
        color_map = {"G1": "#000000", "G2": "#1f77b4", "G3": "#ff7f0e", "G4": "#d62728", "G5": "#2ca02c"}
        graph_df = df[(df[d_col] >= day_range[0]) & (df[d_col] <= day_range[1])].dropna(subset=[w_col])
        df_s = graph_df.groupby([g_col, d_col])[w_col].agg(['mean', 'sem']).reset_index()
        
        fig = go.Figure()
        for g in sorted(df[g_col].unique()):
            data = df_s[df_s[g_col] == g]
            fig.add_trace(go.Scatter(
                x=data[d_col], # 실제 날짜 값 사용
                y=data['mean'], 
                name=g, 
                mode='lines+markers',
                line=dict(color=color_map.get(g, None), width=3),
                error_y=dict(type='data', array=data['sem'], visible=True)
            ))
        
        # [개선] x축을 카테고리가 아닌 선형/실제 숫자축으로 설정
        fig.update_layout(
            xaxis=dict(title="Day (Actual Measured Days)", tickmode='linear', dtick=None),
            yaxis_title=w_col, 
            plot_bgcolor='white'
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- 통계 분석 ---
        st.divider()
        st.subheader(f"🧬 상세 통계 결과 ({target_sel})")
        a_df = df.dropna(subset=[w_col]) if target_sel == "전체 기간(All Days)" else df[df[d_col] == int(target_sel)].dropna(subset=[w_col])
        summary = a_df.groupby(g_col)[w_col].agg(['count', 'mean', 'sem']).reset_index()
        
        st.info(f"💡 **분석 요약:** {st.session_state.summary_text}")
        st.dataframe(summary.style.format(precision=2), use_container_width=True)

        c1, c2, c3 = st.columns(3)
        
        if c1.button("🚀 Dunnett"):
            try:
                others = [g for g in sorted(a_df[g_col].unique()) if g != ctrl_g]
                res = stats.dunnett(*[a_df[a_df[g_col] == g][w_col] for g in others], control=a_df[a_df[g_col] == ctrl_g][w_col])
                res_df = pd.DataFrame({"Comparison": [f"{ctrl_g} vs {g}" for g in others], "p-value": res.pvalue})
                st.session_state.stat_results['Dunnett'] = res_df
                sig = res_df[res_df['p-value'] < 0.05]['Comparison'].tolist()
                st.session_state.summary_text = f"Dunnett 결과, {ctrl_g} 대비 유의차 있는 군: {', '.join(sig) if sig else '없음'}"
                st.rerun()
            except Exception as e: st.error(f"Dunnett 오류: {e}")

        if c2.button("🚀 Tukey HSD"):
            try:
                mc = MultiComparison(a_df[w_col], a_df[g_col])
                res = mc.tukeyhsd()
                res_df = pd.DataFrame(data=res.summary().data[1:], columns=res.summary().data[0])
                st.session_state.stat_results['Tukey'] = res_df
                sig_count = len(res_df[res_df['reject'] == True])
                st.session_state.summary_text = f"Tukey 결과, 총 {sig_count}개의 유의미한 쌍이 발견되었습니다."
                st.rerun()
            except Exception as e: st.error(f"Tukey 오류: {e}")

        if c3.button("🚀 Scheffé"):
            try:
                groups = sorted(a_df[g_col].unique()); results = []
                comb = list(itertools.combinations(groups, 2))
                for g1, g2 in comb:
                    d1, d2 = a_df[a_df[g_col] == g1][w_col], a_df[a_df[g_col] == g2][w_col]
                    diff = np.mean(d1) - np.mean(d2)
                    _, p_val = stats.ttest_ind(d1, d2)
                    adj_p = min(p_val * len(comb), 1.0)
                    results.append({"Group A": g1, "Group B": g2, "Mean Diff": round(diff, 2), "p-adj": adj_p, "Signif": "*" if adj_p < 0.05 else "ns"})
                res_df = pd.DataFrame(results)
                st.session_state.stat_results['Scheffe'] = res_df
                sig_list = res_df[res_df['Signif'] == "*"]
                st.session_state.summary_text = f"Scheffé 결과, 유의미한 차이(*)가 있는 비교 쌍은 {len(sig_list)}개입니다."
                st.rerun()
            except Exception as e: st.error(f"Scheffé 오류: {e}")

        for method, data in st.session_state.stat_results.items():
            st.write(f"**[{method} 상세 결과]**")
            st.dataframe(data, use_container_width=True)

        if st.session_state.stat_results:
            st.sidebar.divider()
            st.sidebar.download_button("📥 통합 리포트 다운로드", data=to_excel_final(summary, st.session_state.stat_results), file_name=f"Analysis_Report.xlsx")

# 4. 관리자 탭
if user_info["role"] == "admin":
    with tabs[1]:
        st.header("⚙️ 데이터 관리")
        up_file = st.file_uploader("파일 업로드", type=['xlsx', 'csv'])
        if st.button("서버 저장"):
            if up_file:
                with open(os.path.join(DATA_DIR, up_file.name), "wb") as f: f.write(up_file.getbuffer())
                st.success("저장 완료!"); st.rerun()

st.sidebar.divider()
if st.sidebar.button("Log Out"):
    st.session_state.logged_in = False
    st.rerun()
