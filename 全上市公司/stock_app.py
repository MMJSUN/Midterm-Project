import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import pickle

st.set_page_config(page_title="MOPS 股市分析儀表板", page_icon="📊", layout="wide")

@st.cache_data
def load():
    try:
        with open("mops_data.pkl", "rb") as f:
            return pickle.load(f)
    except FileNotFoundError:
        # pkl 不存在時，從 mops_master.csv 建立最簡化的資料結構
        import os
        if not os.path.exists("mops_master.csv"):
            return {}
        df = pd.read_csv("mops_master.csv", dtype={"id": str})
        df_is_csv = df.rename(columns={"gross_margin_pct": "gross_margin",
                                        "op_margin_pct":    "op_margin"})
        df_is_csv["year"] = 0
        return {
            "df_is": df_is_csv, "df_bs": df_is_csv,
            "df_div": pd.DataFrame(), "df_cf": pd.DataFrame(),
            "candidates": [], "final": pd.DataFrame(),
            "START_YEAR": 109, "END_YEAR": 113, "YEARS": list(range(109, 114)),
            "thresholds": {}, "_from_csv": True,
        }
raw        = load()
START_YEAR = raw.get("START_YEAR", 109)
END_YEAR   = raw.get("END_YEAR",   113)
candidates = set(str(x) for x in raw.get("candidates", []))
thresholds = raw.get("thresholds", {})

def normalize(df):
    if df.empty:
        return df
    df = df.copy()
    if "id" not in df.columns:
        for c in df.columns:
            if "代號" in str(c):
                df = df.rename(columns={c: "id"})
                break
    if "id" in df.columns:
        df["id"] = df["id"].astype(str).str.extract(r"(\d{4,6})")[0].fillna("")
        df = df[df["id"] != ""]
    return df

df_is  = normalize(raw.get("df_is",  pd.DataFrame()))
df_bs  = normalize(raw.get("df_bs",  pd.DataFrame()))
df_div = normalize(raw.get("df_div", pd.DataFrame()))
df_cf  = normalize(raw.get("df_cf",  pd.DataFrame()))
final  = raw.get("final", pd.DataFrame())

name_map = {}
if not df_is.empty and "id" in df_is.columns and "name" in df_is.columns:
    name_map = df_is.groupby("id")["name"].first().to_dict()

def to_label(code):
    name = name_map.get(str(code), "")
    return f"{code} {name}".strip() if name else str(code)

def add_label(df):
    if df.empty or "id" not in df.columns:
        return df
    df = df.copy()
    df["label"] = df["id"].apply(to_label)
    return df

df_is  = add_label(df_is)
df_bs  = add_label(df_bs)
df_div = add_label(df_div)
df_cf  = add_label(df_cf)

# ── Sidebar ─────────────────────────────────────────────────
st.sidebar.title("📊 MOPS 股市篩選")
st.sidebar.caption(f"分析年度：民國 {START_YEAR}~{END_YEAR}")

# AI 供應鏈主題分類
AI_GROUPS = {
    "晶圓代工與先進封裝"         : ["2330", "3711", "2449"],
    "ASIC 與 IP 設計服務"        : ["2454", "3661", "3443", "3035", "6533"],
    "AI 伺服器代工與系統整合"    : ["2317", "2382", "3231", "6669", "2356", "2301", "2324"],
    "散熱模組與液冷技術"         : ["3017", "3653", "2421", "3013"],
    "電源供應器與綠能電力"       : ["2308", "2303", "6285"],
    "高階導軌與機殼"             : ["2059", "8210", "3693", "3015"],
    "高速傳訊與 IC 晶片"         : ["5269", "4968", "6756"],
    "高階 PCB、銅箔基板與 ABF 載板": ["2383", "3037", "2368", "6213", "3189", "8046"],
}
ALL_AI_IDS = [i for ids in AI_GROUPS.values() for i in ids]

# 全部公司（來自爬取資料）
if not df_is.empty and "id" in df_is.columns:
    all_ids = sorted(df_is["id"].dropna().unique().tolist())
elif not df_bs.empty and "id" in df_bs.columns:
    all_ids = sorted(df_bs["id"].dropna().unique().tolist())
else:
    all_ids = []

if not all_ids:
    st.error("找不到公司清單，請先執行 Notebook Cell 1~11")
    st.stop()

all_labels  = [to_label(i) for i in all_ids]
cand_labels = [to_label(i) for i in all_ids if i in candidates]

show_mode = st.sidebar.radio(
    "顯示範圍",
    ["僅篩選通過", "AI供應鏈分類", "全部公司", "自訂選擇"],
    index=0,
)

if show_mode == "僅篩選通過":
    sel_labels = cand_labels if cand_labels else all_labels[:min(10, len(all_labels))]

elif show_mode == "AI供應鏈分類":
    sel_groups = st.sidebar.multiselect(
        "選擇 AI 供應鏈類別",
        list(AI_GROUPS.keys()),
        default=list(AI_GROUPS.keys()),
    )
    ai_ids_raw = [i for g in sel_groups for i in AI_GROUPS[g]]
    seen_set = set()
    ai_ids_unique = [x for x in ai_ids_raw if x not in seen_set and not seen_set.add(x)]
    sel_labels = [to_label(i) for i in ai_ids_unique if i in set(all_ids)]
    if not sel_labels:
        sel_labels = cand_labels[:min(10, len(cand_labels))]

elif show_mode == "全部公司":
    sel_labels = all_labels

else:  # 自訂選擇
    sel_labels = st.sidebar.multiselect(
        "選擇公司 (代號 + 名稱)",
        all_labels,
        default=cand_labels[:min(8, len(cand_labels))] or all_labels[:8],
    )

selected = [lbl.split(" ")[0] for lbl in sel_labels]

year_range = st.sidebar.slider("年度範圍", START_YEAR, END_YEAR, (START_YEAR, END_YEAR))
st.sidebar.markdown("---")

# 篩選條件說明
if thresholds:
    st.sidebar.subheader("篩選條件")
    st.sidebar.markdown(f"""
- EPS > 0 連續年
- 營業利益率 > {thresholds.get('OP_MARGIN_THRESHOLD', 0.10)*100:.0f}%
- 負債比 < {thresholds.get('DEBT_THRESHOLD', 0.50)*100:.0f}%
- ROE > {thresholds.get('ROE_THRESHOLD', 0.10)*100:.0f}%
- 毛利率/營業利益率趨勢相關係數下限 > -0.10
    """)
st.sidebar.info("重新爬取後執行 Cell 11 更新資料，再重啟 App")

if not selected:
    st.warning("請在左側選擇至少一家公司")
    st.stop()

def flt(df):
    if df.empty or "id" not in df.columns or "year" not in df.columns:
        return df
    return df[df["id"].isin(selected) & df["year"].between(year_range[0], year_range[1])].copy()

is_f  = flt(df_is)
bs_f  = flt(df_bs)
div_f = flt(df_div)
cf_f  = flt(df_cf)

# ── 頁面標題 + KPI ─────────────────────────────────────────
st.title("📊 MOPS 上市公司財務分析儀表板")
if not is_f.empty and "eps" in is_f.columns:
    lat  = is_f[is_f["year"] == is_f["year"].max()]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("顯示公司數", len(selected))
    k2.metric("平均 EPS", f"{lat['eps'].mean():.2f} 元")
    k3.metric("平均毛利率",
              f"{lat['gross_margin'].mean()*100:.1f}%" if "gross_margin" in lat else "—")
    if not bs_f.empty and "roe" in bs_f.columns:
        k4.metric("平均 ROE",
                  f"{bs_f[bs_f['year']==bs_f['year'].max()]['roe'].mean()*100:.1f}%")
    else:
        k4.metric("全部公司數", len(all_ids))
st.markdown("---")

t1, t2, t3, t4, t5 = st.tabs(
    ["🏆 篩選總覽", "📈 損益趨勢", "🏦 資產負債", "💰 股利分析", "💵 現金流量"])

# ── Tab1：篩選總覽 ───────────────────────────────────────────
with t1:
    # 直接從目前選取範圍建表，顯示所有 selected 公司，不限篩選通過
    if not is_f.empty:
        lat_is = is_f[is_f["year"] == is_f["year"].max()].copy()
        avg_e  = (is_f.groupby("id")["eps"].mean()
                  .reset_index().rename(columns={"eps": "avg_eps"}))
        tab1_df = lat_is[[c for c in ["id", "label", "name", "eps",
                                       "gross_margin", "op_margin"]
                           if c in lat_is.columns]].copy()
        tab1_df = tab1_df.merge(avg_e, on="id", how="left")
        if not bs_f.empty:
            lat_bs  = bs_f[bs_f["year"] == bs_f["year"].max()]
            bs_need = ["id"] + [c for c in ["debt_ratio", "roe"] if c in lat_bs.columns]
            tab1_df = tab1_df.merge(lat_bs[bs_need], on="id", how="left")
        for col, pct in [("gross_margin", "毛利率%"), ("op_margin", "營業利益率%"),
                          ("debt_ratio",   "負債比%"),  ("roe",       "ROE%")]:
            if col in tab1_df.columns:
                tab1_df[pct] = (tab1_df[col] * 100).round(1)
        show_cols = (
            [c for c in ["label", "name"] if c in tab1_df.columns] +
            [c for c in ["avg_eps", "eps", "毛利率%", "營業利益率%", "負債比%", "ROE%"]
             if c in tab1_df.columns]
        )
        st.dataframe(
            tab1_df[show_cols]
              .rename(columns={"name": "公司名稱",
                               "avg_eps": "平均EPS", "label": "代號+名稱"})
              .reset_index(drop=True),
            use_container_width=True, height=400
        )
    if not is_f.empty and not bs_f.empty:
        li = is_f[is_f["year"] == is_f["year"].max()].copy()
        lb = bs_f[bs_f["year"] == bs_f["year"].max()].copy()
        need = ["id", "debt_ratio"] + (["roe"] if "roe" in lb.columns else [])
        need = [c for c in need if c in lb.columns]
        cols_i = [c for c in ["id", "label", "name", "eps", "gross_margin", "op_margin"] if c in li.columns]
        mg = li[cols_i].merge(lb[need], on="id", how="left") if "id" in li.columns else pd.DataFrame()
        if not mg.empty:
            if "gross_margin" in mg: mg["gm%"] = (mg["gross_margin"]*100).round(1)
            if "op_margin"    in mg: mg["op%"] = (mg["op_margin"]   *100).round(1)
            if "debt_ratio"   in mg: mg["dr%"] = (mg["debt_ratio"]  *100).round(1)
            if "roe"          in mg: mg["roe%"]= (mg["roe"]         *100).round(1)
            if "is_cand" not in mg.columns:
                mg["篩選通過"] = mg["id"].isin(candidates).map({True:"✅通過",False:"❌未通過"})
            mg["AI分類"] = mg["id"].apply(
                lambda x: next((g for g, ids in AI_GROUPS.items() if x in ids), "其他"))
            txt_col = "label" if "label" in mg.columns else "id"
            c1, c2 = st.columns(2)
            with c1:
                if "roe%" in mg and "dr%" in mg:
                    fig = px.scatter(mg, x="dr%", y="roe%", text=txt_col,
                        color="篩選通過" if "篩選通過" in mg else "roe%",
                        color_discrete_map={"✅通過":"#00CC96","❌未通過":"#EF553B"},
                        title="ROE vs 負債比率",
                        labels={"dr%":"負債比(%)","roe%":"ROE(%)"})
                    fig.update_traces(textposition="top center", marker_size=10)
                    fig.add_vline(x=50, line_dash="dash", line_color="red")
                    fig.add_hline(y=10, line_dash="dash", line_color="green")
                    st.plotly_chart(fig, use_container_width=True)
            with c2:
                if "gm%" in mg and "op%" in mg:
                    fig2 = px.scatter(mg, x="gm%", y="op%", text=txt_col,
                        color="篩選通過" if "篩選通過" in mg else None,
                        color_discrete_map={"✅通過":"#00CC96","❌未通過":"#EF553B"},
                        title="毛利率 vs 營業利益率",
                        labels={"gm%":"毛利率(%)","op%":"營業利益率(%)"})
                    fig2.add_hline(y=10, line_dash="dash", line_color="orange",
                                   annotation_text="10%基準")
                    fig2.update_traces(textposition="top center", marker_size=10)
                    st.plotly_chart(fig2, use_container_width=True)

# ── Tab2：損益趨勢 ───────────────────────────────────────────
with t2:
    if is_f.empty:
        st.info("無損益表資料")
    else:
        ip  = is_f.sort_values("year")
        lbl = "label" if "label" in ip.columns else "id"
        c1, c2 = st.columns(2)
        with c1:
            if "eps" in ip.columns:
                fe = px.line(ip, x="year", y="eps", color=lbl, markers=True,
                    title="EPS 歷年趨勢",
                    labels={"year":"民國年","eps":"EPS(元)",lbl:"公司"})
                fe.add_hline(y=0, line_dash="dash", line_color="red")
                st.plotly_chart(fe, use_container_width=True)
        with c2:
            if "gross_margin" in ip.columns:
                fg = px.line(ip, x="year", y="gross_margin", color=lbl, markers=True,
                    title="毛利率歷年趨勢",
                    labels={"year":"民國年","gross_margin":"毛利率",lbl:"公司"})
                fg.update_yaxes(tickformat=".1%")
                st.plotly_chart(fg, use_container_width=True)
        if "op_margin" in ip.columns:
            fo = px.line(ip, x="year", y="op_margin", color=lbl, markers=True,
                title="營業利益率歷年趨勢",
                labels={"year":"民國年","op_margin":"營業利益率",lbl:"公司"})
            fo.update_yaxes(tickformat=".1%")
            fo.add_hline(y=0.10, line_dash="dash", line_color="orange",
                         annotation_text="10%基準")
            st.plotly_chart(fo, use_container_width=True)
        if "eps" in ip.columns:
            st.subheader("各年 EPS 比較")
            fb = px.bar(ip, x=lbl, y="eps", color="year", barmode="group",
                title="各公司 EPS 分年比較",
                labels={lbl:"公司","eps":"EPS(元)","year":"民國年"})
            st.plotly_chart(fb, use_container_width=True)

# ── Tab3：資產負債 ───────────────────────────────────────────
with t3:
    if bs_f.empty:
        st.info("無資產負債表資料")
    else:
        bp  = bs_f.sort_values("year")
        lbl = "label" if "label" in bp.columns else "id"
        c1, c2 = st.columns(2)
        with c1:
            if "debt_ratio" in bp.columns:
                fd = px.line(bp, x="year", y="debt_ratio", color=lbl, markers=True,
                    title="負債比率歷年趨勢",
                    labels={"year":"民國年","debt_ratio":"負債比率",lbl:"公司"})
                fd.update_yaxes(tickformat=".1%")
                fd.add_hline(y=0.5, line_dash="dash", line_color="red",
                             annotation_text="50%上限")
                st.plotly_chart(fd, use_container_width=True)
        with c2:
            if "roe" in bp.columns:
                fr = px.line(bp, x="year", y="roe", color=lbl, markers=True,
                    title="ROE 歷年趨勢",
                    labels={"year":"民國年","roe":"ROE",lbl:"公司"})
                fr.update_yaxes(tickformat=".1%")
                fr.add_hline(y=0.10, line_dash="dash", line_color="green",
                             annotation_text="10%基準")
                st.plotly_chart(fr, use_container_width=True)
        st.subheader("資產結構 (最新年度)")
        lb2 = bp[bp["year"] == bp["year"].max()].copy()
        if "assets" in lb2.columns and "liabilities" in lb2.columns:
            lb2["equity_v"] = lb2["assets"] - lb2["liabilities"]
            x_col = "label" if "label" in lb2.columns else "id"
            stk = lb2[[x_col, "liabilities", "equity_v"]].melt(
                id_vars=x_col, var_name="項目", value_name="金額")
            stk["項目"] = stk["項目"].map({"liabilities":"負債","equity_v":"股東權益"})
            fs = px.bar(stk, x=x_col, y="金額", color="項目", barmode="stack",
                title="資產 = 負債 + 股東權益",
                color_discrete_map={"負債":"#EF553B","股東權益":"#00CC96"},
                labels={x_col:"公司"})
            st.plotly_chart(fs, use_container_width=True)

# ── Tab4：股利分析 ───────────────────────────────────────────
with t4:
    if div_f.empty:
        st.info("無股利資料（Cell 6 尚未成功抓取）")
    else:
        lbl = "label" if "label" in div_f.columns else "id"
        cash_col = next((c for c in div_f.columns if "現金股利" in str(c) and "元" in str(c)),
                        "cash_div" if "cash_div" in div_f.columns else None)
        if cash_col:
            dp = div_f[div_f[cash_col].notna()].copy()
            dp["cdv"] = pd.to_numeric(dp[cash_col], errors="coerce")
            da = dp.groupby(["id","year","label"] if "label" in dp.columns else ["id","year"])["cdv"].max().reset_index()
            if not da.empty:
                lbl_da = "label" if "label" in da.columns else "id"
                fdb = px.bar(da, x="year", y="cdv", color=lbl_da, barmode="group",
                    title="各公司現金股利 (元/股)",
                    labels={"year":"民國年","cdv":"現金股利(元/股)",lbl_da:"公司"})
                st.plotly_chart(fdb, use_container_width=True)
                fdl = px.line(da, x="year", y="cdv", color=lbl_da, markers=True,
                    title="現金股利趨勢",
                    labels={"year":"民國年","cdv":"現金股利(元/股)",lbl_da:"公司"})
                st.plotly_chart(fdl, use_container_width=True)
        if "has_dividend" in div_f.columns:
            st.subheader("配息年份熱力圖")
            piv_src = div_f.copy()
            piv_src["y_key"] = piv_src["label"] if "label" in piv_src.columns else piv_src["id"]
            piv = piv_src.groupby(["y_key","year"])["has_dividend"].any().unstack(fill_value=False).astype(int)
            fh = px.imshow(piv, title="配息紀錄 (綠=有 紅=無)",
                color_continuous_scale=["#EF553B","#00CC96"], aspect="auto",
                labels={"x":"民國年","y":"公司","color":"配息"})
            fh.update_coloraxes(showscale=False)
            st.plotly_chart(fh, use_container_width=True)

# ── Tab5：現金流量 ───────────────────────────────────────────
with t5:
    if cf_f.empty:
        st.info("無現金流量資料（Cell 現金流量表 尚未成功抓取）")
    else:
        cp  = cf_f.sort_values("year")
        lbl = "label" if "label" in cp.columns else "id"
        c1, c2 = st.columns(2)
        with c1:
            if "ocf" in cp.columns:
                foc = px.line(cp, x="year", y="ocf", color=lbl, markers=True,
                    title="營業現金流歷年趨勢 (萬元)",
                    labels={"year":"民國年","ocf":"營業現金流(萬)",lbl:"公司"})
                foc.add_hline(y=0, line_dash="dash", line_color="red")
                st.plotly_chart(foc, use_container_width=True)
        with c2:
            if "fcf" in cp.columns:
                ffc = px.line(cp, x="year", y="fcf", color=lbl, markers=True,
                    title="自由現金流歷年趨勢 (萬元)",
                    labels={"year":"民國年","fcf":"自由現金流(萬)",lbl:"公司"})
                ffc.add_hline(y=0, line_dash="dash", line_color="red")
                st.plotly_chart(ffc, use_container_width=True)
        if "ocf" in cp.columns:
            lat_cf = cp[cp["year"] == cp["year"].max()]
            lbl_cf = "label" if "label" in lat_cf.columns else "id"
            fcf_cols = [lbl_cf, "ocf"] + (["fcf"] if "fcf" in lat_cf.columns else [])
            st.subheader(f"最新年度現金流量比較 (民國 {cp['year'].max()})")
            st.dataframe(
                lat_cf[fcf_cols].rename(columns={"ocf":"營業現金流(萬)","fcf":"自由現金流(萬)",lbl_cf:"公司"})
                .sort_values("營業現金流(萬)", ascending=False)
                .reset_index(drop=True),
                use_container_width=True
            )

